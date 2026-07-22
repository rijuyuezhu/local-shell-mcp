"""Shell command, Python snippet, and persistent session operation helpers."""

import asyncio
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .. import conpty
from ..audit import audit
from ..config.settings import get_settings
from ..schemas.result_models.shell import (
    CommandResult,
    KillPersistentShellOutput,
    ListPersistentShellsOutput,
    ReadPersistentShellOutput,
    ResizePersistentShellOutput,
    RunPythonCodeOutput,
    RunShellCommandOutput,
    SendPersistentShellInputOutput,
    ShellExecutionOutput,
    StartPersistentShellOutput,
)
from ..tmux_helper import require_tmux
from ..tool_session.store import (
    get_tool_session_store,
    resolve_session_path,
)
from ..utils.serialization import to_jsonable
from .utils.path import (
    relative_display,
    resolve_path,
)
from .utils.remote_session import call_remote_session_tool
from .utils.temp_file import write_temp_text_file

GRACEFUL_TERMINATION_TIMEOUT_S = 5
KILL_TERMINATION_TIMEOUT_S = 2
READER_DRAIN_TIMEOUT_S = 2
TOOL_WATCHDOG_SCHEDULING_MARGIN_S = 1
SHELL_TIMEOUT_CLEANUP_GRACE_S = (
    GRACEFUL_TERMINATION_TIMEOUT_S
    + KILL_TERMINATION_TIMEOUT_S
    + READER_DRAIN_TIMEOUT_S
    + TOOL_WATCHDOG_SCHEDULING_MARGIN_S
)
SHELL_TIMEOUT_CLEANUP_TOOL_NAMES = frozenset({"bash", "run_python_code"})
INTERNAL_SHELL_DEFAULT_TIMEOUT_S = 60
INTERNAL_SHELL_MAX_TIMEOUT_S = 3600
PERSISTENT_SHELL_MIN_COLUMNS = 20
PERSISTENT_SHELL_MAX_COLUMNS = 1600
PERSISTENT_SHELL_MIN_ROWS = 3
PERSISTENT_SHELL_MAX_ROWS = 500
_COMMAND_SEMAPHORE: asyncio.Semaphore | None = None
_COMMAND_SEMAPHORE_SIZE: int | None = None


def _env_name(*parts: str) -> str:
    return "".join(parts)


FROZEN_LOADER_ENV_VARS = (
    _env_name("LD", "_", "LIBRARY", "_", "PATH"),
    _env_name("LD", "_", "PRE", "LOAD"),
    _env_name("DYLD", "_", "LIBRARY", "_", "PATH"),
    _env_name("DYLD", "_", "INSERT", "_", "LIBRARIES"),
)


def _is_frozen_app() -> bool:
    """Return whether this process is running from a frozen app bundle."""
    return bool(getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None))


def _restore_or_remove_loader_var(env: dict[str, str], name: str) -> None:
    original_name = f"{name}_ORIG"
    original_value = env.pop(original_name, None)
    if original_value:
        env[name] = original_value
    else:
        env.pop(name, None)


_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class TailBuffer:
    """Accumulate bounded process output while tracking how many bytes were dropped from the head."""

    keep_bytes: int
    """Maximum number of output bytes retained in memory."""
    data: bytearray
    """Buffered tail bytes retained from process output."""
    total_bytes: int = 0
    """Total bytes observed before tail truncation."""

    def append(self, chunk: bytes) -> None:
        """Append bytes to the tail buffer and discard the oldest data beyond the configured limit."""
        if not chunk:
            return
        self.total_bytes += len(chunk)
        self.data.extend(chunk)
        overflow = len(self.data) - self.keep_bytes
        if overflow > 0:
            del self.data[:overflow]

    @property
    def truncated(self) -> bool:
        """Report whether any output was dropped while enforcing the buffer limit."""
        return self.total_bytes > len(self.data)


def _shared_tail_bytes(
    stdout: bytes, stderr: bytes, limit: int
) -> tuple[bytes, bytes, bool]:
    """Fit two stream tails into one byte budget without wasting idle-stream capacity."""
    total = len(stdout) + len(stderr)
    if total <= limit:
        return stdout, stderr, False

    stdout_keep = min(len(stdout), limit // 2)
    stderr_keep = min(len(stderr), limit // 2)
    remaining = limit - stdout_keep - stderr_keep
    if remaining > 0:
        stdout_extra = min(remaining, len(stdout) - stdout_keep)
        stdout_keep += stdout_extra
        remaining -= stdout_extra
    if remaining > 0:
        stderr_keep += min(remaining, len(stderr) - stderr_keep)

    return (
        stdout[-stdout_keep:] if stdout_keep else b"",
        stderr[-stderr_keep:] if stderr_keep else b"",
        True,
    )


def check_command_policy(command: str) -> None:
    """Reject shell commands matching configured denylist entries before execution."""
    settings = get_settings()
    normalized = command.casefold()
    for denied in settings.command_denylist:
        if denied and denied.casefold() in normalized:
            raise PermissionError(
                f"Command contains denylisted fragment: {denied!r}"
            )


def _effective_shell_default_timeout_s() -> int:
    """Return the effective internal shell default timeout."""
    return max(
        1,
        INTERNAL_SHELL_DEFAULT_TIMEOUT_S,
        get_settings().run_shell_default_timeout_s,
    )


def _effective_shell_max_timeout_s() -> int:
    """Return the effective internal shell timeout cap."""
    return max(
        1, INTERNAL_SHELL_MAX_TIMEOUT_S, get_settings().run_shell_max_timeout_s
    )


def clamp_timeout(timeout_s: int | None) -> int:
    """Clamp requested internal command timeouts to the effective server bounds."""
    timeout = timeout_s or _effective_shell_default_timeout_s()
    return max(1, min(timeout, _effective_shell_max_timeout_s()))


def run_shell_command_timeout(timeout_s: int | None) -> int:
    """Resolve bounded shell command timeout from configured defaults and caps."""
    settings = get_settings()
    default = max(1, settings.run_shell_default_timeout_s)
    cap = max(1, settings.run_shell_max_timeout_s)
    if timeout_s is not None and timeout_s > cap:
        raise ValueError(
            f"timeout_s must be <= {cap} seconds for bounded shell commands; "
            "use bash async or PTY mode for long-running or streaming commands"
        )
    return max(1, min(timeout_s or default, cap))


def tool_timeout_s(tool_name: str | None = None) -> float:
    """Return the effective MCP/HTTP watchdog timeout for one tool."""
    settings = get_settings()
    configured = max(0.001, settings.tool_timeout_s)
    if tool_name == "apply_patch":
        from .patch import APPLY_PATCH_WATCHDOG_TIMEOUT_S

        return max(configured, float(APPLY_PATCH_WATCHDOG_TIMEOUT_S))
    if tool_name not in SHELL_TIMEOUT_CLEANUP_TOOL_NAMES:
        return configured
    cleanup_safe_shell_timeout = (
        max(1, settings.run_shell_max_timeout_s) + SHELL_TIMEOUT_CLEANUP_GRACE_S
    )
    return max(configured, float(cleanup_safe_shell_timeout))


def _effective_output_limit(max_output_bytes: int | None = None) -> int:
    """Resolve the output byte limit requested by a caller against server-wide maximums."""
    settings = get_settings()
    configured = max(1, settings.max_output_bytes)
    if max_output_bytes is None:
        return configured
    return max(1, min(max_output_bytes, configured))


def _command_semaphore() -> asyncio.Semaphore:
    """Return the process-wide semaphore that limits concurrent shell commands."""
    global _COMMAND_SEMAPHORE, _COMMAND_SEMAPHORE_SIZE
    size = max(1, get_settings().max_concurrent_commands)
    if _COMMAND_SEMAPHORE is None or size != _COMMAND_SEMAPHORE_SIZE:
        _COMMAND_SEMAPHORE = asyncio.Semaphore(size)
        _COMMAND_SEMAPHORE_SIZE = size
    return _COMMAND_SEMAPHORE


def _subprocess_env() -> dict[str, str]:
    """Return the environment exposed to user shell commands."""
    blocked_names = {
        "CLOUDFLARE_TUNNEL_TOKEN",
        "PYTHONPATH",
    }
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in blocked_names
        and not key.startswith("LOCAL_SHELL_MCP_")
        and not key.startswith("DOCKER_")
    }
    if _is_frozen_app():
        for name in FROZEN_LOADER_ENV_VARS:
            _restore_or_remove_loader_var(env, name)
    return env


def _effective_shell_executable() -> str:
    """Return a usable configured shell, adapting the POSIX default on Windows."""
    configured = str(get_settings().shell_executable).strip()
    if os.name == "nt" and configured in {"", "/bin/bash"}:
        return os.environ.get("COMSPEC") or "cmd.exe"
    return configured or os.environ.get("SHELL") or "/bin/sh"


def _shell_command_args(shell: str, command: str) -> list[str]:
    """Build native argv for POSIX shells, PowerShell, or cmd.exe."""
    name = os.path.basename(shell).lower()
    if name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        return [shell, "-NoProfile", "-NonInteractive", "-Command", command]
    if name in {"cmd", "cmd.exe"}:
        return [shell, "/D", "/S", "/C", command]
    return [shell, "-lc", command]


def _shell_join_argv(argv: list[str]) -> str:
    """Render argv for the native shell without losing Windows quoting."""
    return (
        subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    )


def _effective_python_executable() -> str:
    """Return a usable Python executable, adapting the POSIX default on Windows."""
    configured = str(get_settings().python_bin).strip()
    if os.name == "nt" and configured in {"", "python3"}:
        return sys.executable or "python"
    return configured or sys.executable


def _validated_env_overrides(env: dict[str, str] | None) -> dict[str, str]:
    """Validate and normalize caller-provided subprocess environment overrides."""
    if not env:
        return {}
    normalized: dict[str, str] = {}
    for name, value in env.items():
        if not _ENV_NAME_RE.match(name):
            raise ValueError(f"Invalid environment variable name: {name!r}")
        normalized[name] = str(value)
    return normalized


async def _spawn_process(
    command: str,
    cwd: str,
    env: dict[str, str] | None = None,
) -> asyncio.subprocess.Process:
    """Start a native shell command in its own process group."""
    shell = _effective_shell_executable()
    child_env = _subprocess_env()
    child_env.update(_validated_env_overrides(env))
    process_group: dict[str, Any]
    if os.name == "nt":
        process_group = {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
        }
    else:
        process_group = {"start_new_session": True}
    common: dict[str, Any] = {
        "cwd": cwd,
        "env": child_env,
        "stdin": asyncio.subprocess.DEVNULL,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        **process_group,
    }
    shell_name = os.path.basename(shell).lower()
    if shell_name in {"cmd", "cmd.exe"}:
        return await asyncio.create_subprocess_shell(
            command,
            executable=shell,
            **common,
        )
    return await asyncio.create_subprocess_exec(
        *_shell_command_args(shell, command),
        **common,
    )


async def _read_stream_tail(
    stream: asyncio.StreamReader | None, tail: TailBuffer
) -> None:
    """Continuously read a process stream into a bounded tail buffer."""
    if stream is None:
        return
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            return
        tail.append(chunk)


async def _wait_for_process_exit(
    proc: asyncio.subprocess.Process, timeout_s: int
) -> bool:
    """Wait for process completion while converting timeout into structured result state."""
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_s)
        return True
    except TimeoutError:
        return False


async def _terminate_process_group(proc: asyncio.subprocess.Process) -> str:
    """Terminate an entire shell process group, escalating to kill when graceful shutdown times out."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        proc.terminate()

    output = await _wait_for_process_exit(proc, GRACEFUL_TERMINATION_TIMEOUT_S)
    if output:
        return ""

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        proc.kill()

    output = await _wait_for_process_exit(proc, KILL_TERMINATION_TIMEOUT_S)
    if output:
        return ""
    return "Process did not exit after SIGKILL"


async def _finish_reader_tasks(
    tasks: list[asyncio.Task[None]], timeout_s: float = READER_DRAIN_TIMEOUT_S
) -> None:
    """Let stream-reader tasks drain briefly before cancelling unfinished readers."""
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout_s)
    except TimeoutError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def run_shell(
    command: str,
    cwd: str = ".",
    timeout_s: int | None = None,
    max_output_bytes: int | None = None,
    env: dict[str, str] | None = None,
) -> CommandResult:
    """Execute a shell command with policy enforcement, concurrency limits, timeout handling, and bounded output capture."""
    check_command_policy(command)
    resolved_cwd = resolve_path(cwd, must_exist=True)
    start = time.time()
    audit("run_shell_command_start", command=command, cwd=str(resolved_cwd))
    timeout = clamp_timeout(timeout_s)

    proc: asyncio.subprocess.Process | None = None
    timed_out = False
    termination_error = ""
    output_limit = _effective_output_limit(max_output_bytes)
    stdout_tail = TailBuffer(output_limit, bytearray())
    stderr_tail = TailBuffer(output_limit, bytearray())
    reader_tasks: list[asyncio.Task[None]] = []

    async def spawn_and_wait() -> None:
        nonlocal proc
        proc = await _spawn_process(command, str(resolved_cwd), env)
        reader_tasks.extend(
            [
                asyncio.create_task(
                    _read_stream_tail(proc.stdout, stdout_tail)
                ),
                asyncio.create_task(
                    _read_stream_tail(proc.stderr, stderr_tail)
                ),
            ]
        )
        await proc.wait()

    semaphore = _command_semaphore()
    acquired = False
    try:
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=timeout)
            acquired = True
            elapsed = max(0.0, time.time() - start)
            remaining_timeout = max(0.001, timeout - elapsed)
            await asyncio.wait_for(spawn_and_wait(), timeout=remaining_timeout)
        except TimeoutError:
            timed_out = True
            if proc is None:
                reader_tasks = []
                termination_error = "Timed out while starting subprocess"
            else:
                termination_error = await _terminate_process_group(proc)
        except asyncio.CancelledError:
            if proc is not None:
                await asyncio.shield(_terminate_process_group(proc))
            raise
    finally:
        if acquired:
            semaphore.release()

    if reader_tasks:
        await _finish_reader_tasks(reader_tasks)

    if termination_error:
        stderr_tail.append(termination_error.encode())

    stdout_b, stderr_b, total_truncated = _shared_tail_bytes(
        bytes(stdout_tail.data), bytes(stderr_tail.data), output_limit
    )
    stdout = stdout_b.decode(errors="replace")
    stderr = stderr_b.decode(errors="replace")
    truncated = (
        stdout_tail.truncated or stderr_tail.truncated or total_truncated
    )
    duration_ms = int((time.time() - start) * 1000)
    result = CommandResult(
        ok=(proc is not None and proc.returncode == 0 and not timed_out),
        exit_code=proc.returncode if proc is not None else None,
        timed_out=timed_out,
        duration_ms=duration_ms,
        cwd=relative_display(resolved_cwd),
        command=command,
        stdout=stdout,
        stderr=stderr,
        truncated=truncated,
    )
    audit(
        "run_shell_command_end",
        command=command,
        cwd=str(resolved_cwd),
        exit_code=proc.returncode if proc is not None else None,
        timed_out=timed_out,
        duration_ms=duration_ms,
        truncated=truncated,
    )
    return result


async def run_shell_command_execute(
    command: str,
    cwd: str = ".",
    timeout_s: int | None = None,
    max_output_bytes: int | None = None,
    env: dict[str, str] | None = None,
) -> RunShellCommandOutput:
    """Execute a shell command through the public API using stricter timeout defaults."""
    result = await run_shell(
        command,
        cwd,
        run_shell_command_timeout(timeout_s),
        max_output_bytes,
        env,
    )
    return RunShellCommandOutput(**result.model_dump())


def _command_with_env(command: str, env: dict[str, str] | None) -> str:
    """Prefix PTY/job commands with shell-native environment assignments."""
    overrides = _validated_env_overrides(env)
    if not overrides:
        return command
    shell_name = os.path.basename(_effective_shell_executable()).lower()
    if shell_name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        assignments = [
            f"$env:{name}='{value.replace(chr(39), chr(39) * 2)}'"
            for name, value in overrides.items()
        ]
        return f"{'; '.join(assignments)}; {command}"
    if shell_name in {"cmd", "cmd.exe"}:
        assignments = [
            f'set "{name}={value}"' for name, value in overrides.items()
        ]
        return f"{' && '.join(assignments)} && {command}"
    assignments = [
        f"{name}={shlex.quote(value)}" for name, value in overrides.items()
    ]
    return f"{' '.join(assignments)} {command}"


def _as_result_dict(value: Any) -> dict[str, Any]:
    """Return a JSON-compatible result dictionary."""
    data = to_jsonable(value)
    return data if isinstance(data, dict) else {"result": data}


async def bash_execute(
    session_id: str,
    command: str,
    cwd: str = ".",
    timeout_s: int | None = None,
    max_output_bytes: int | None = None,
    env: dict[str, str] | None = None,
    async_: bool = False,
    pty: bool = False,
    name: str | None = None,
) -> ShellExecutionOutput:
    """Run a shell command via bounded, tracked-job, or PTY mode inside a session."""
    session = get_tool_session_store().touch_session(session_id)
    if session.target == "remote":
        if pty:
            raise ValueError(
                "PTY shell mode is not available for remote sessions; "
                "use bounded commands or async jobs instead"
            )
        data = await call_remote_session_tool(
            session,
            "bash",
            {
                "command": command,
                "cwd": cwd,
                "timeout_s": timeout_s,
                "max_output_bytes": max_output_bytes,
                "env": env,
                "async_": async_,
                "pty": pty,
                "name": name,
            },
            timeout_s if isinstance(timeout_s, int) else None,
        )
        return ShellExecutionOutput.model_validate(data)

    resolved_cwd = resolve_session_path(session, cwd, must_exist=True)
    cwd_text = str(resolved_cwd)
    command_with_env = _command_with_env(command, env)
    if pty:
        result = await start_persistent_shell_execute(
            cwd_text, name, command_with_env
        )
        return ShellExecutionOutput(
            mode="pty",
            command=command,
            cwd=cwd_text,
            result=_as_result_dict(result),
        )
    if async_:
        from .jobs import job_start_execute

        result = await job_start_execute(
            session_id, command_with_env, cwd_text, name
        )
        return ShellExecutionOutput(
            mode="job",
            command=command,
            cwd=cwd_text,
            result=_as_result_dict(result),
        )
    result = await run_shell_command_execute(
        command, cwd_text, timeout_s, max_output_bytes, env
    )
    return ShellExecutionOutput(
        mode="command",
        command=command,
        cwd=cwd_text,
        result=_as_result_dict(result),
    )


async def run_python_code_execute(
    session_id: str,
    code: str,
    cwd: str = ".",
    timeout_s: int | None = None,
    max_output_bytes: int | None = None,
    env: dict[str, str] | None = None,
    async_: bool = False,
    pty: bool = False,
    name: str | None = None,
) -> RunPythonCodeOutput:
    """Write Python code to a temporary file and execute it through shell modes."""
    session = get_tool_session_store().touch_session(session_id)
    if session.target == "remote":
        data = await call_remote_session_tool(
            session,
            "run_python_code",
            {
                "code": code,
                "cwd": cwd,
                "timeout_s": timeout_s,
                "max_output_bytes": max_output_bytes,
                "env": env,
                "async_": async_,
                "pty": pty,
                "name": name,
            },
            timeout_s if isinstance(timeout_s, int) else None,
        )
        return RunPythonCodeOutput.model_validate(data)

    resolved_cwd = resolve_session_path(session, cwd, must_exist=True)
    script_path = await write_temp_text_file(
        "Python script", code, "script", "py"
    )
    command = _shell_join_argv(
        [_effective_python_executable(), str(script_path)]
    )
    result = await bash_execute(
        session_id,
        command,
        str(resolved_cwd),
        timeout_s,
        max_output_bytes,
        env,
        async_,
        pty,
        name,
    )
    return RunPythonCodeOutput(
        **result.model_dump(), script_path=str(script_path)
    )


def _tmux_session_name(name: str | None = None) -> str:
    """Normalize user-facing shell names into the tmux naming scheme used by the server."""
    base = name or f"mcp-{uuid.uuid4().hex[:8]}"
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "-", base.strip())[:64].strip(".-")
    return cleaned or f"mcp-{uuid.uuid4().hex[:8]}"


async def tmux(args: list[str], timeout_s: int = 10) -> CommandResult:
    """Run a tmux command with a bounded timeout and normalized command result payload."""
    selection = require_tmux()
    cmd = " ".join(shlex.quote(x) for x in [selection.path, *args])
    return await run_shell(cmd, cwd=".", timeout_s=timeout_s)


def _use_conpty_persistent_shell_backend() -> bool:
    """Return whether persistent shells should use the Windows ConPTY backend."""
    return os.name == "nt"


async def start_persistent_shell_execute(
    cwd: str = ".", name: str | None = None, command: str | None = None
) -> StartPersistentShellOutput:
    """Start a platform-native persistent shell in a resolved working directory."""
    resolved_cwd = resolve_path(cwd, must_exist=True)
    shells = await list_persistent_shells_execute()
    max_sessions = max(1, get_settings().max_tmux_sessions)
    if len(shells.shells) >= max_sessions:
        raise RuntimeError(
            f"Refusing to start more than {max_sessions} persistent shell sessions"
        )
    shell_id = _tmux_session_name(name)
    if _use_conpty_persistent_shell_backend():
        if not conpty.is_available():
            raise RuntimeError(
                "pywinpty is required for persistent shells on Windows"
            )
        initial = conpty.initial_command(command)
        check_command_policy(initial)
        return await conpty.start_shell(
            shell_id=shell_id,
            cwd=resolved_cwd,
            command=command,
        )

    initial = command or get_settings().shell_executable
    check_command_policy(initial)
    cmd = [
        "new-session",
        "-d",
        "-s",
        shell_id,
        "-c",
        str(resolved_cwd),
        initial,
    ]
    result = await tmux(cmd)
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout)
    audit(
        "start_persistent_shell",
        shell_id=shell_id,
        cwd=str(resolved_cwd),
        command=initial,
        backend="tmux",
    )
    return StartPersistentShellOutput(
        shell_id=shell_id,
        cwd=relative_display(resolved_cwd),
        command=initial,
        backend="tmux",
    )


async def send_persistent_shell_input_execute(
    shell_id: str, input_text: str, enter: bool = True
) -> SendPersistentShellInputOutput:
    """Send input to a persistent shell, optionally appending Enter."""
    if _use_conpty_persistent_shell_backend():
        return await conpty.send_shell(shell_id, input_text, enter)
    if input_text:
        result = await tmux(["send-keys", "-l", "-t", shell_id, input_text])
        if not result.ok:
            raise RuntimeError(result.stderr or result.stdout)
    if enter:
        result = await tmux(["send-keys", "-t", shell_id, "Enter"])
        if not result.ok:
            raise RuntimeError(result.stderr or result.stdout)
    audit(
        "send_persistent_shell_input",
        shell_id=shell_id,
        bytes=len(input_text.encode()),
        enter=enter,
        backend="tmux",
    )
    return SendPersistentShellInputOutput(
        shell_id=shell_id,
        sent_bytes=len(input_text.encode()),
        enter=enter,
    )


def _validate_persistent_shell_size(cols: int, rows: int) -> tuple[int, int]:
    columns = int(cols)
    lines = int(rows)
    if (
        not PERSISTENT_SHELL_MIN_COLUMNS
        <= columns
        <= PERSISTENT_SHELL_MAX_COLUMNS
    ):
        raise ValueError(
            f"cols must be between {PERSISTENT_SHELL_MIN_COLUMNS} and "
            f"{PERSISTENT_SHELL_MAX_COLUMNS}"
        )
    if not PERSISTENT_SHELL_MIN_ROWS <= lines <= PERSISTENT_SHELL_MAX_ROWS:
        raise ValueError(
            f"rows must be between {PERSISTENT_SHELL_MIN_ROWS} and "
            f"{PERSISTENT_SHELL_MAX_ROWS}"
        )
    return columns, lines


async def resize_persistent_shell_execute(
    shell_id: str, cols: int, rows: int
) -> ResizePersistentShellOutput:
    """Resize one persistent terminal when supported by its backend."""
    columns, lines = _validate_persistent_shell_size(cols, rows)
    if _use_conpty_persistent_shell_backend():
        return await conpty.resize_shell(shell_id, columns, lines)
    result = await tmux(
        [
            "resize-window",
            "-t",
            shell_id,
            "-x",
            str(columns),
            "-y",
            str(lines),
        ]
    )
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout)
    audit(
        "resize_persistent_shell",
        shell_id=shell_id,
        cols=columns,
        rows=lines,
        backend="tmux",
    )
    return ResizePersistentShellOutput(
        shell_id=shell_id,
        cols=columns,
        rows=lines,
        resized=True,
        backend="tmux",
    )


async def read_persistent_shell_output_execute(
    shell_id: str,
    lines: int = 200,
    *,
    preserve_ansi: bool = False,
) -> ReadPersistentShellOutput:
    """Read recent output from a persistent shell."""
    if _use_conpty_persistent_shell_backend():
        return await conpty.read_shell(
            shell_id,
            lines,
            preserve_ansi=preserve_ansi,
        )
    capture_args = ["capture-pane", "-p"]
    if preserve_ansi:
        capture_args.append("-e")
    capture_args.extend(["-t", shell_id, "-S", f"-{max(1, lines)}"])
    result = await tmux(capture_args)
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout)
    audit(
        "read_persistent_shell_output",
        shell_id=shell_id,
        lines=lines,
        preserve_ansi=preserve_ansi,
        backend="tmux",
    )
    return ReadPersistentShellOutput(
        shell_id=shell_id,
        output=result.stdout,
        lines=lines,
        backend="tmux",
    )


async def kill_persistent_shell_execute(
    shell_id: str,
) -> KillPersistentShellOutput:
    """Terminate a persistent shell by its normalized shell id."""
    if _use_conpty_persistent_shell_backend():
        return await conpty.kill_shell(shell_id)
    result = await tmux(["kill-session", "-t", shell_id])
    audit(
        "kill_persistent_shell",
        shell_id=shell_id,
        ok=result.ok,
        backend="tmux",
    )
    return KillPersistentShellOutput(
        shell_id=shell_id,
        killed=result.ok,
        stderr=result.stderr,
        backend="tmux",
    )


async def list_persistent_shells_execute() -> ListPersistentShellsOutput:
    """List active persistent shells managed by local-shell-mcp."""
    if _use_conpty_persistent_shell_backend():
        return await conpty.list_shells()
    result = await tmux(
        [
            "list-sessions",
            "-F",
            "#{session_name}\t#{session_created}\t#{session_attached}",
        ],
        timeout_s=5,
    )
    if not result.ok:
        return ListPersistentShellsOutput(shells=[])
    shells = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if parts:
            shells.append(
                {
                    "shell_id": parts[0],
                    "created": parts[1] if len(parts) > 1 else None,
                    "attached": parts[2] if len(parts) > 2 else None,
                    "backend": "tmux",
                }
            )
    return ListPersistentShellsOutput(shells=shells)
