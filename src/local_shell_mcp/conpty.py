"""Windows ConPTY-backed persistent shells and raw terminal attachments."""

from __future__ import annotations

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

from .audit import audit
from .config.settings import get_settings
from .ops.utils.path import relative_display
from .schemas.result_models.shell import (
    KillPersistentShellOutput,
    ListPersistentShellsOutput,
    PersistentShellInfo,
    ReadPersistentShellOutput,
    ResizePersistentShellOutput,
    SendPersistentShellInputOutput,
    StartPersistentShellOutput,
)

CONPTY_BACKEND = "conpty"
CONPTY_BUFFER_BYTES = 1_000_000
CONPTY_RAW_BUFFER_BYTES = 1_000_000
CONPTY_READ_CHARS = 65_536
CONPTY_DEFAULT_COLUMNS = 120
CONPTY_DEFAULT_ROWS = 36
_CONPTY_WRITE_RETRIES = 50
_CONPTY_WRITE_RETRY_S = 0.01
_SHELL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")

try:  # pragma: no cover - imported only on Windows installations.
    import winpty  # pyright: ignore[reportMissingImports]
except ImportError:  # pragma: no cover - exercised through mocked module state.
    winpty = None


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
    cwd: Path
    command: str
    created: int
    output: _TailBuffer = field(
        default_factory=lambda: _TailBuffer(CONPTY_BUFFER_BYTES)
    )
    state_lock: threading.RLock = field(default_factory=threading.RLock)
    io_lock: threading.Lock = field(default_factory=threading.Lock)
    subscribers: dict[str, _RawSubscriber] = field(default_factory=dict)
    reader: threading.Thread | None = None
    closing: bool = False

    def alive(self) -> bool:
        with self.state_lock:
            return not self.closing and _pty_is_alive(self.process)

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
            while self.alive():
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
            with _SESSIONS_LOCK:
                if _SESSIONS.get(self.shell_id) is self:
                    _SESSIONS.pop(self.shell_id, None)

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
        if not already_closing:
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
        return error


_SESSIONS: dict[str, _ConPtySession] = {}
_SESSIONS_LOCK = threading.RLock()


def has_session(shell_id: str) -> bool:
    """Return whether one live ConPTY persistent shell is registered."""
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(shell_id)
    return session is not None and session.alive()


def _get_session(shell_id: str) -> _ConPtySession:
    if not _SHELL_ID_PATTERN.fullmatch(shell_id):
        raise RuntimeError(f"Persistent shell session not found: {shell_id}")
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(shell_id)
    if session is None:
        raise RuntimeError(f"Persistent shell session not found: {shell_id}")
    if not session.alive():
        with _SESSIONS_LOCK:
            if _SESSIONS.get(shell_id) is session:
                _SESSIONS.pop(shell_id, None)
        session.close(force=False)
        raise RuntimeError(f"Persistent shell session exited: {shell_id}")
    return session


async def start_shell(
    *,
    shell_id: str,
    cwd: Path,
    command: str | None,
) -> StartPersistentShellOutput:
    """Start and register one Windows ConPTY persistent shell."""
    if not is_available():
        raise RuntimeError("pywinpty is not available")
    if not _SHELL_ID_PATTERN.fullmatch(shell_id):
        raise ValueError("Invalid persistent shell id")
    with _SESSIONS_LOCK:
        stale = [key for key, value in _SESSIONS.items() if not value.alive()]
        stale_sessions = [_SESSIONS.pop(key) for key in stale]
    for stale_session in stale_sessions:
        await asyncio.to_thread(stale_session.close, force=False)
    with _SESSIONS_LOCK:
        if shell_id in _SESSIONS:
            raise RuntimeError(
                f"Persistent shell session already exists: {shell_id}"
            )
    initial = initial_command(command)
    process = await asyncio.to_thread(
        _spawn_pty,
        _persistent_shell_args(command),
        cwd,
        CONPTY_DEFAULT_COLUMNS,
        CONPTY_DEFAULT_ROWS,
    )
    session = _ConPtySession(
        shell_id=shell_id,
        process=process,
        cwd=cwd,
        command=initial,
        created=int(time.time()),
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
    try:
        session.start_reader()
    except Exception:
        with _SESSIONS_LOCK:
            if _SESSIONS.get(shell_id) is session:
                _SESSIONS.pop(shell_id, None)
        await asyncio.to_thread(session.close, force=True)
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
        session = _SESSIONS.pop(shell_id, None)
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
        stale = [key for key, value in _SESSIONS.items() if not value.alive()]
        stale_sessions = [_SESSIONS.pop(key) for key in stale]
        sessions = list(_SESSIONS.values())
    for stale_session in stale_sessions:
        await asyncio.to_thread(stale_session.close, force=False)
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
