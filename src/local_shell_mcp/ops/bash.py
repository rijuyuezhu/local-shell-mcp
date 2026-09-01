"""Session-aware shell and Python execution facade."""

import contextlib
import os
import shlex
from typing import Any

from ..jobs import runtime as jobs_runtime
from ..schemas.result_models.shell import (
    RunPythonCodeOutput,
    ShellExecutionOutput,
)
from ..tool_session.lifecycle import session_lifecycle_lock
from ..tool_session.store import get_tool_session_store, resolve_session_path
from ..utils.serialization import to_jsonable
from .shell import (
    _effective_python_executable,
    _effective_shell_executable,
    _shell_join_argv,
    _validated_env_overrides,
    kill_persistent_shell_execute,
    run_shell_command_execute,
    start_persistent_shell_execute,
)
from .utils.remote_session import call_remote_session_tool
from .utils.temp_file import write_temp_text_file


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
    if pty:
        async with session_lifecycle_lock(session_id):
            session = get_tool_session_store().touch_session(session_id)
            if session.target == "remote":
                raise ValueError(
                    "PTY shell mode is not available for remote sessions; "
                    "use bounded commands or async jobs instead"
                )
            resolved_cwd = resolve_session_path(session, cwd, must_exist=True)
            cwd_text = str(resolved_cwd)
            command_with_env = _command_with_env(command, env)
            result = await start_persistent_shell_execute(
                cwd_text,
                name,
                command_with_env,
                owner_session_id=session_id,
            )
            try:
                get_tool_session_store().register_persistent_shell(
                    session_id, result.shell_id
                )
            except BaseException:
                with contextlib.suppress(Exception):
                    await kill_persistent_shell_execute(result.shell_id)
                raise
            return ShellExecutionOutput(
                mode="pty",
                command=command,
                cwd=cwd_text,
                result=_as_result_dict(result),
            )

    if not async_:
        async with session_lifecycle_lock(session_id):
            session = get_tool_session_store().touch_session(session_id)
            if session.target == "remote":
                data = await call_remote_session_tool(
                    session,
                    "bash",
                    {
                        "command": command,
                        "cwd": cwd,
                        "timeout_s": timeout_s,
                        "max_output_bytes": max_output_bytes,
                        "env": env,
                        "async_": False,
                        "pty": False,
                        "name": name,
                    },
                    timeout_s if isinstance(timeout_s, int) else None,
                )
                return ShellExecutionOutput.model_validate(data)
            resolved_cwd = resolve_session_path(session, cwd, must_exist=True)
            cwd_text = str(resolved_cwd)
            result = await run_shell_command_execute(
                command, cwd_text, timeout_s, max_output_bytes, env
            )
            return ShellExecutionOutput(
                mode="command",
                command=command,
                cwd=cwd_text,
                result=_as_result_dict(result),
            )

    session = get_tool_session_store().touch_session(session_id)
    if session.target == "remote":
        async with session_lifecycle_lock(session_id):
            session = get_tool_session_store().touch_session(session_id)
            data = await call_remote_session_tool(
                session,
                "bash",
                {
                    "command": command,
                    "cwd": cwd,
                    "timeout_s": timeout_s,
                    "max_output_bytes": max_output_bytes,
                    "env": env,
                    "async_": True,
                    "pty": False,
                    "name": name,
                },
                timeout_s if isinstance(timeout_s, int) else None,
            )
            return ShellExecutionOutput.model_validate(data)

    resolved_cwd = resolve_session_path(session, cwd, must_exist=True)
    cwd_text = str(resolved_cwd)
    command_with_env = _command_with_env(command, env)
    result = await jobs_runtime.job_start_execute(
        session_id, command_with_env, cwd_text, name
    )
    return ShellExecutionOutput(
        mode="job",
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
        async with session_lifecycle_lock(session_id):
            session = get_tool_session_store().touch_session(session_id)
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
