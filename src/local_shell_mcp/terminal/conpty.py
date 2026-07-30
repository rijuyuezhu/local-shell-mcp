"""Windows ConPTY-backed persistent shells and raw terminal attachments."""

import asyncio
import codecs
import contextlib
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..audit import audit
from ..config.settings import get_settings
from ..errors import process_start_not_found_error
from ..ops.utils.path import relative_display
from ..persistence import get_state_store
from ..schemas.result_models.shell import (
    KillPersistentShellOutput,
    ListPersistentShellsOutput,
    PersistentShellInfo,
    ReadPersistentShellOutput,
    ResizePersistentShellOutput,
    SendPersistentShellInputOutput,
    StartPersistentShellOutput,
)
from ..utils.private_files import private_file_lock

CONPTY_BACKEND = "conpty"
CONPTY_BUFFER_BYTES = 1_000_000
CONPTY_RAW_BUFFER_BYTES = 1_000_000
CONPTY_READ_CHARS = 65_536
CONPTY_DEFAULT_COLUMNS = 120
CONPTY_DEFAULT_ROWS = 36
_CONPTY_WRITE_RETRIES = 50
_CONPTY_WRITE_RETRY_S = 0.01
_CONPTY_LEASE_ACQUIRE_TIMEOUT_S = 5.0
_CONPTY_LEASE_JOIN_TIMEOUT_S = 5.0
_CONPTY_LEASE_PREFIX = "conpty-shell-"
_SHELL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class ConPtyCleanupUncertainError(RuntimeError):
    """A failed ConPTY start may still have a live backend process."""


try:  # pragma: no cover - imported only on Windows installations.
    import winpty  # pyright: ignore[reportMissingImports]
except ImportError:  # pragma: no cover - exercised through mocked module state.
    winpty = None


def _shell_lease_path(shell_id: str) -> Path:
    """Return one owner-private cross-process lease path for a shell id."""
    directory = get_state_store().layout.locks_dir
    directory.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        directory.chmod(0o700)
    return directory / f"{_CONPTY_LEASE_PREFIX}{shell_id}.lock"


class _ConPtyShellLease:
    """Hold one ConPTY shell liveness lock in a dedicated native thread."""

    def __init__(self, shell_id: str) -> None:
        self.shell_id = str(shell_id)
        self.path = _shell_lease_path(self.shell_id)
        self._acquired = threading.Event()
        self._release = threading.Event()
        self._error: BaseException | None = None
        self._state_lock = threading.Lock()
        self._released = False
        self._thread = threading.Thread(
            target=self._run,
            name=f"conpty-shell-lease-{self.shell_id}",
            daemon=True,
        )

    def _run(self) -> None:
        try:
            with private_file_lock(
                self.path,
                timeout_s=_CONPTY_LEASE_ACQUIRE_TIMEOUT_S,
            ):
                self._acquired.set()
                self._release.wait()
        except BaseException as exc:
            self._error = exc
            self._acquired.set()

    def acquire(self) -> None:
        """Acquire the lease before spawning the ConPTY process."""
        self._thread.start()
        if not self._acquired.wait(_CONPTY_LEASE_ACQUIRE_TIMEOUT_S + 1.0):
            self._release.set()
            self._thread.join(_CONPTY_LEASE_JOIN_TIMEOUT_S)
            if self._thread.is_alive():
                raise RuntimeError(
                    "ConPTY shell lease acquisition timed out and the lease "
                    "thread did not exit"
                )
            raise RuntimeError("ConPTY shell lease acquisition timed out")
        if self._error is not None:
            raise self._error
        if not self._thread.is_alive():
            raise RuntimeError("ConPTY shell lease exited before acquisition")

    def release(self) -> None:
        """Release the lease and wait for any concurrent release to finish."""
        with self._state_lock:
            if not self._released:
                self._released = True
                self._release.set()
        self._thread.join(_CONPTY_LEASE_JOIN_TIMEOUT_S)
        if self._thread.is_alive():
            raise RuntimeError("ConPTY shell lease did not exit")
        if self._error is not None:
            raise self._error


def authoritative_shell_ids() -> set[str] | None:
    """Return shell ids with live cross-process ConPTY leases."""
    directory = get_state_store().layout.locks_dir
    try:
        directory.mkdir(parents=True, exist_ok=True)
        paths = sorted(directory.glob(f"{_CONPTY_LEASE_PREFIX}*.lock"))
    except OSError:
        return None
    active: set[str] = set()
    for path in paths:
        name = path.name
        shell_id = name[len(_CONPTY_LEASE_PREFIX) : -len(".lock")]
        if not _SHELL_ID_PATTERN.fullmatch(shell_id):
            continue
        try:
            with private_file_lock(path, timeout_s=0.0):
                pass
        except TimeoutError:
            active.add(shell_id)
        except OSError:
            return None
    return active


def _is_windows() -> bool:
    return os.name == "nt"


def is_available() -> bool:
    """Return whether a usable pywinpty ConPTY implementation is installed."""
    return (
        _is_windows() and winpty is not None and hasattr(winpty, "PtyProcess")
    )


def _shell_program_name(shell: str) -> str:
    return shell.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _shell_executable() -> str:
    configured = str(get_settings().shell_executable).strip()
    if configured and not (_is_windows() and configured == "/bin/bash"):
        return configured
    return os.environ.get("COMSPEC") or "cmd.exe"


def _shell_command_args(shell: str, command: str) -> list[str]:
    name = _shell_program_name(shell)
    powershell = "power" + "shell"
    if name in {powershell, f"{powershell}.exe", "pwsh", "pwsh.exe"}:
        return [shell, "-NoProfile", "-NonInteractive", "-Command", command]
    if name in {"cmd", "cmd.exe"}:
        return [shell, "/S", "/C", command]
    return [shell, "-lc", command]


def initial_command(command: str | None) -> str:
    """Return the command recorded and policy-checked for a ConPTY shell."""
    return command or _shell_executable()


def _persistent_shell_args(command: str | None) -> list[str]:
    shell = _shell_executable()
    if command:
        return _shell_command_args(shell, command)
    return [shell]


def _subprocess_env() -> dict[str, str]:
    blocked_names = {"CLOUDFLARE_TUNNEL_TOKEN", "PYTHONPATH"}
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in blocked_names
        and not key.startswith("LOCAL_SHELL_MCP_")
        and not key.startswith("DOCKER_")
    }
    env.setdefault("TERM", "xterm-256color")
    env["COLORTERM"] = "truecolor"
    return env


def _spawn_pty(argv: list[str], cwd: Path, cols: int, rows: int) -> Any:
    if not is_available():
        raise RuntimeError("pywinpty is not available")
    assert winpty is not None
    spawn = winpty.PtyProcess.spawn
    dimensions = (max(1, rows), max(1, cols))
    env = _subprocess_env()
    candidates: tuple[list[str] | str, ...] = (
        argv,
        subprocess.list2cmdline(argv),
    )
    last_error: TypeError | None = None
    for command in candidates:
        try:
            return spawn(
                command,
                cwd=str(cwd),
                env=env,
                dimensions=dimensions,
            )
        except TypeError as exc:
            last_error = exc
    for command in candidates:
        try:
            process = spawn(command, cwd=str(cwd), env=env)
            resize = getattr(process, "setwinsize", None)
            if callable(resize):
                resize(dimensions[0], dimensions[1])
            return process
        except TypeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("Unable to start ConPTY process")


def _pty_is_alive(process: Any) -> bool:
    isalive = getattr(process, "isalive", None)
    if callable(isalive):
        with contextlib.suppress(Exception):
            return bool(isalive())
    return getattr(process, "exitstatus", None) is None


def _read_pty(process: Any) -> str | bytes:
    try:
        return process.read(CONPTY_READ_CHARS)
    except TypeError:
        return process.read()


def _close_pty_process(process: Any, force: bool) -> None:
    close = getattr(process, "close", None)
    if callable(close):
        if getattr(process, "closed", False):
            with contextlib.suppress(Exception):
                process.closed = False
        try:
            close(force=force)
        except TypeError:
            close()
        return
    terminate = getattr(process, "terminate", None)
    if callable(terminate):
        try:
            terminate(force=force)
        except TypeError:
            terminate()


def _strip_terminal_controls(value: str) -> str:
    value = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", value)
    value = re.sub(r"\x1b[P^_X][\s\S]*?\x1b\\", "", value)
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    value = re.sub(r"\x1b[@-_]", "", value)
    value = value.replace("\x1b", "")
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)


@dataclass
class _TailBuffer:
    keep_bytes: int
    data: bytearray = field(default_factory=bytearray)
    total_bytes: int = 0

    def append(self, chunk: bytes) -> None:
        self.total_bytes += len(chunk)
        self.data.extend(chunk)
        del self.data[: max(0, len(self.data) - self.keep_bytes)]


class _RawSubscriber:
    def __init__(self, initial: bytes) -> None:
        self._condition = threading.Condition()
        self._data = bytearray(initial[-CONPTY_RAW_BUFFER_BYTES:])
        self._eof = False

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return
        with self._condition:
            if self._eof:
                return
            self._data.extend(chunk)
            overflow = len(self._data) - CONPTY_RAW_BUFFER_BYTES
            if overflow > 0:
                del self._data[:overflow]
                self._eof = True
            self._condition.notify_all()

    def finish(self) -> None:
        with self._condition:
            self._eof = True
            self._condition.notify_all()

    def read_wait(self, max_bytes: int, wait_ms: int) -> tuple[bytes, bool]:
        timeout = max(0.0, wait_ms / 1000.0)
        deadline = time.monotonic() + timeout
        with self._condition:
            while not self._data and not self._eof:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            count = min(max_bytes, len(self._data))
            data = bytes(self._data[:count])
            if count:
                del self._data[:count]
            return data, self._eof and not self._data


@dataclass
class _ConPtySession:
    shell_id: str
    process: Any
    lease: _ConPtyShellLease
    cwd: Path
    command: str
    created: int
    owner_session_id: str | None = None
    output: _TailBuffer = field(
        default_factory=lambda: _TailBuffer(CONPTY_BUFFER_BYTES)
    )
    state_lock: threading.RLock = field(default_factory=threading.RLock)
    io_lock: threading.Lock = field(default_factory=threading.Lock)
    subscribers: dict[str, _RawSubscriber] = field(default_factory=dict)
    reader: threading.Thread | None = None
    closing: bool = False

    def process_alive(self) -> bool:
        """Return whether the underlying process is still present."""
        return _pty_is_alive(self.process)

    def alive(self) -> bool:
        """Return whether the shell remains available for interactive use."""
        with self.state_lock:
            return not self.closing and self.process_alive()

    def _finalize_terminated_process(self) -> str:
        """Release registry state only after process death is confirmed."""
        if self.process_alive():
            return "ConPTY process termination was not confirmed"
        try:
            self.lease.release()
        except Exception as exc:
            return repr(exc)
        with _SESSIONS_LOCK:
            if _SESSIONS.get(self.shell_id) is self:
                _SESSIONS.pop(self.shell_id, None)
        return ""

    def start_reader(self) -> None:
        reader = threading.Thread(
            target=self._reader_main,
            name=f"lsm-conpty-{self.shell_id}",
            daemon=True,
        )
        self.reader = reader
        reader.start()

    def _reader_main(self) -> None:
        try:
            while self.process_alive():
                chunk = _read_pty(self.process)
                if not chunk:
                    if not _pty_is_alive(self.process):
                        break
                    time.sleep(0.02)
                    continue
                data = (
                    chunk.encode("utf-8", errors="replace")
                    if isinstance(chunk, str)
                    else bytes(chunk)
                )
                with self.state_lock:
                    self.output.append(data)
                    subscribers = tuple(self.subscribers.values())
                for subscriber in subscribers:
                    subscriber.feed(data)
        except Exception:
            pass
        finally:
            with self.state_lock:
                should_close_process = not self.closing
                self.closing = True
                subscribers = tuple(self.subscribers.values())
                self.subscribers.clear()
            for subscriber in subscribers:
                subscriber.finish()
            if should_close_process:
                with contextlib.suppress(Exception):
                    _close_pty_process(self.process, True)
            self._finalize_terminated_process()

    def output_snapshot(self) -> bytes:
        with self.state_lock:
            return bytes(self.output.data)

    def attached(self) -> bool:
        with self.state_lock:
            return bool(self.subscribers)

    def subscribe(self, attachment_id: str) -> _RawSubscriber:
        with self.state_lock:
            if self.closing or not _pty_is_alive(self.process):
                raise RuntimeError(
                    f"Persistent shell session exited: {self.shell_id}"
                )
            subscriber = _RawSubscriber(bytes(self.output.data))
            self.subscribers[attachment_id] = subscriber
            return subscriber

    def unsubscribe(self, attachment_id: str) -> None:
        with self.state_lock:
            subscriber = self.subscribers.pop(attachment_id, None)
        if subscriber is not None:
            subscriber.finish()

    def write_text(self, text: str) -> None:
        if not text:
            return
        with self.io_lock:
            if not self.alive():
                raise RuntimeError("Terminal bridge is unavailable")
            for attempt in range(_CONPTY_WRITE_RETRIES):
                try:
                    result = self.process.write(text)
                except BlockingIOError:
                    if attempt + 1 == _CONPTY_WRITE_RETRIES:
                        raise
                    time.sleep(_CONPTY_WRITE_RETRY_S)
                    continue
                if result is not None and (
                    not isinstance(result, int) or result < 0
                ):
                    raise OSError(
                        "Unexpected ConPTY write result: "
                        f"{type(result).__name__}"
                    )
                return
        raise OSError("ConPTY write did not complete")

    def resize(self, cols: int, rows: int) -> bool:
        resize = getattr(self.process, "setwinsize", None)
        if not callable(resize):
            return False
        with self.io_lock:
            if not self.alive():
                raise RuntimeError("Terminal bridge is unavailable")
            resize(max(1, rows), max(1, cols))
        return True

    def close(self, *, force: bool) -> str:
        with self.state_lock:
            already_closing = self.closing
            if not already_closing:
                self.closing = True
                subscribers = tuple(self.subscribers.values())
                self.subscribers.clear()
            else:
                subscribers = ()
        for subscriber in subscribers:
            subscriber.finish()
        error = ""
        if self.process_alive():
            try:
                _close_pty_process(self.process, force)
            except Exception as exc:
                error = repr(exc)
        reader = self.reader
        if (
            reader is not None
            and reader is not threading.current_thread()
            and reader.is_alive()
        ):
            reader.join(timeout=2)
        finalize_error = self._finalize_terminated_process()
        if finalize_error:
            error = f"{error}; {finalize_error}" if error else finalize_error
        return error


_SESSIONS: dict[str, _ConPtySession] = {}
_SESSIONS_LOCK = threading.RLock()


def has_session(shell_id: str) -> bool:
    """Return whether one live ConPTY shell remains, reaping dead state."""
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(shell_id)
    if session is None:
        return False
    if session.process_alive():
        return True
    session.close(force=False)
    return False


def _get_session(shell_id: str) -> _ConPtySession:
    if not _SHELL_ID_PATTERN.fullmatch(shell_id):
        raise RuntimeError(f"Persistent shell session not found: {shell_id}")
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(shell_id)
    if session is None:
        raise RuntimeError(f"Persistent shell session not found: {shell_id}")
    if not session.process_alive():
        session.close(force=False)
        raise RuntimeError(f"Persistent shell session exited: {shell_id}")
    if not session.alive():
        raise RuntimeError(f"Persistent shell session is closing: {shell_id}")
    return session


async def start_shell(
    *,
    shell_id: str,
    cwd: Path,
    command: str | None,
    owner_session_id: str | None = None,
) -> StartPersistentShellOutput:
    """Start and register one Windows ConPTY persistent shell."""
    if not is_available():
        raise RuntimeError("pywinpty is not available")
    if not _SHELL_ID_PATTERN.fullmatch(shell_id):
        raise ValueError("Invalid persistent shell id")
    with _SESSIONS_LOCK:
        stale_sessions = [
            value for value in _SESSIONS.values() if not value.process_alive()
        ]
    for stale_session in stale_sessions:
        await asyncio.to_thread(stale_session.close, force=False)
    with _SESSIONS_LOCK:
        if shell_id in _SESSIONS:
            raise RuntimeError(
                f"Persistent shell session already exists: {shell_id}"
            )
    initial = initial_command(command)
    args = _persistent_shell_args(command)
    lease = _ConPtyShellLease(shell_id)
    cancelled: asyncio.CancelledError | None = None
    try:
        await asyncio.to_thread(lease.acquire)
        spawn_task = asyncio.create_task(
            asyncio.to_thread(
                _spawn_pty,
                args,
                cwd,
                CONPTY_DEFAULT_COLUMNS,
                CONPTY_DEFAULT_ROWS,
            )
        )
        try:
            process = await asyncio.shield(spawn_task)
        except asyncio.CancelledError as exc:
            cancelled = exc
            while not spawn_task.done():
                try:
                    await asyncio.shield(spawn_task)
                except asyncio.CancelledError:
                    continue
            process = spawn_task.result()
        except FileNotFoundError as exc:
            raise process_start_not_found_error(
                exc,
                executable=str(args[0]),
                command=initial,
                cwd=cwd,
            ) from exc
    except BaseException:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(lease.release)
        raise
    session = _ConPtySession(
        shell_id=shell_id,
        process=process,
        lease=lease,
        cwd=cwd,
        command=initial,
        created=int(time.time()),
        owner_session_id=owner_session_id,
    )
    with _SESSIONS_LOCK:
        duplicate = shell_id in _SESSIONS
        if not duplicate:
            _SESSIONS[shell_id] = session
    if duplicate:
        await asyncio.to_thread(session.close, force=True)
        raise RuntimeError(
            f"Persistent shell session already exists: {shell_id}"
        )
    if cancelled is not None:
        cleanup_task = asyncio.create_task(
            asyncio.to_thread(session.close, force=True)
        )
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                continue
        cleanup_error = cleanup_task.result()
        if cleanup_error:
            raise ConPtyCleanupUncertainError(
                "ConPTY startup was cancelled and cleanup was not confirmed: "
                f"{shell_id}: {cleanup_error}"
            ) from cancelled
        raise cancelled
    try:
        session.start_reader()
    except Exception as exc:
        cleanup_error = await asyncio.to_thread(session.close, force=True)
        if cleanup_error:
            raise ConPtyCleanupUncertainError(
                "ConPTY startup failed and cleanup was not confirmed: "
                f"{shell_id}: {cleanup_error}"
            ) from exc
        raise
    audit(
        "start_persistent_shell",
        shell_id=shell_id,
        cwd=str(cwd),
        command=initial,
        backend=CONPTY_BACKEND,
    )
    return StartPersistentShellOutput(
        shell_id=shell_id,
        cwd=relative_display(cwd),
        command=initial,
        backend=CONPTY_BACKEND,
    )


async def send_shell(
    shell_id: str, input_text: str, enter: bool
) -> SendPersistentShellInputOutput:
    """Send normalized terminal text to one ConPTY persistent shell."""
    session = _get_session(shell_id)
    data = input_text + ("\r" if enter else "")
    await asyncio.to_thread(session.write_text, data)
    audit(
        "send_persistent_shell_input",
        shell_id=shell_id,
        bytes=len(input_text.encode()),
        enter=enter,
        backend=CONPTY_BACKEND,
    )
    return SendPersistentShellInputOutput(
        shell_id=shell_id,
        sent_bytes=len(input_text.encode()),
        enter=enter,
    )


async def resize_shell(
    shell_id: str, cols: int, rows: int
) -> ResizePersistentShellOutput:
    """Resize one ConPTY shell when pywinpty exposes resize support."""
    session = _get_session(shell_id)
    resized = await asyncio.to_thread(session.resize, cols, rows)
    audit(
        "resize_persistent_shell",
        shell_id=shell_id,
        cols=cols,
        rows=rows,
        resized=resized,
        backend=CONPTY_BACKEND,
    )
    return ResizePersistentShellOutput(
        shell_id=shell_id,
        cols=cols,
        rows=rows,
        resized=resized,
        backend=CONPTY_BACKEND,
    )


async def read_shell(
    shell_id: str,
    lines: int,
    *,
    preserve_ansi: bool,
) -> ReadPersistentShellOutput:
    """Read a bounded plain-text or ANSI snapshot from one ConPTY shell."""
    session = _get_session(shell_id)
    raw = session.output_snapshot()
    output = raw.decode("utf-8", errors="replace")
    if not preserve_ansi:
        output = _strip_terminal_controls(output)
    if lines > 0:
        split = output.splitlines()
        output = "\n".join(split[-max(1, lines) :]) if split else ""
        if raw.endswith((b"\n", b"\r")) and output:
            output += "\n"
    audit(
        "read_persistent_shell_output",
        shell_id=shell_id,
        lines=lines,
        preserve_ansi=preserve_ansi,
        backend=CONPTY_BACKEND,
    )
    return ReadPersistentShellOutput(
        shell_id=shell_id,
        output=output,
        lines=lines,
        backend=CONPTY_BACKEND,
    )


async def kill_shell(shell_id: str) -> KillPersistentShellOutput:
    """Terminate and deregister one ConPTY persistent shell."""
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(shell_id)
    if session is None:
        return KillPersistentShellOutput(
            shell_id=shell_id,
            killed=False,
            stderr="Persistent shell session not found",
            backend=CONPTY_BACKEND,
        )
    error = await asyncio.to_thread(session.close, force=True)
    audit(
        "kill_persistent_shell",
        shell_id=shell_id,
        ok=not error,
        backend=CONPTY_BACKEND,
    )
    return KillPersistentShellOutput(
        shell_id=shell_id,
        killed=not error,
        stderr=error,
        backend=CONPTY_BACKEND,
    )


async def list_shells() -> ListPersistentShellsOutput:
    """List live ConPTY persistent shells and reap stale entries."""
    with _SESSIONS_LOCK:
        stale_sessions = [
            value for value in _SESSIONS.values() if not value.process_alive()
        ]
    for stale_session in stale_sessions:
        await asyncio.to_thread(stale_session.close, force=False)
    with _SESSIONS_LOCK:
        sessions = [
            session for session in _SESSIONS.values() if session.process_alive()
        ]
    return ListPersistentShellsOutput(
        shells=[
            PersistentShellInfo.model_validate(
                {
                    "shell_id": session.shell_id,
                    "created": str(session.created),
                    "attached": "1" if session.attached() else "0",
                    "backend": CONPTY_BACKEND,
                    "cwd": relative_display(session.cwd),
                    "command": session.command,
                }
            )
            for session in sessions
        ]
    )


async def list_owned_shell_ids(owner_session_id: str) -> list[str]:
    """Return live ConPTY shell ids owned by one explicit agent session."""
    await list_shells()
    with _SESSIONS_LOCK:
        return sorted(
            session.shell_id
            for session in _SESSIONS.values()
            if session.owner_session_id == owner_session_id
        )


class ConPtyRawAttachment:
    """One exclusive raw subscriber attached to a persistent ConPTY shell."""

    backend = CONPTY_BACKEND
    """Terminal bridge backend identifier exposed to protocol normalizers."""

    def __init__(
        self,
        session: _ConPtySession,
        attachment_id: str,
        subscriber: _RawSubscriber,
    ) -> None:
        self.shell_id = session.shell_id
        self._session = session
        self._attachment_id = attachment_id
        self._subscriber = subscriber
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._lock = threading.Lock()
        self._closed = False

    def read_wait(self, max_bytes: int, wait_ms: int) -> tuple[bytes, bool]:
        """Read a bounded raw output chunk, waiting briefly when empty."""
        return self._subscriber.read_wait(max_bytes, wait_ms)

    def write_all(self, data: bytes) -> None:
        """Decode and deliver one complete bounded UTF-8 input chunk."""
        if not data:
            return
        with self._lock:
            if self._closed:
                raise RuntimeError("Terminal bridge is unavailable")
            text = self._decoder.decode(data, final=False)
            if text:
                self._session.write_text(text)

    def resize(self, cols: int, rows: int) -> bool:
        """Resize the underlying ConPTY shell when supported."""
        with self._lock:
            if self._closed:
                raise RuntimeError("Terminal bridge is unavailable")
        return self._session.resize(cols, rows)

    def close_sync(self) -> None:
        """Detach this raw subscriber without terminating its shell."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._session.unsubscribe(self._attachment_id)


def open_raw_attachment(
    shell_id: str,
    attachment_id: str,
    cols: int,
    rows: int,
) -> ConPtyRawAttachment:
    """Open one exclusive raw subscriber for a ConPTY persistent shell."""
    session = _get_session(shell_id)
    session.resize(cols, rows)
    subscriber = session.subscribe(attachment_id)
    return ConPtyRawAttachment(session, attachment_id, subscriber)


def reset_conpty_sessions_for_tests() -> None:
    """Force-close and clear all process-scoped ConPTY test sessions."""
    with _SESSIONS_LOCK:
        sessions = list(_SESSIONS.values())
        _SESSIONS.clear()
    for session in sessions:
        session.close(force=True)
