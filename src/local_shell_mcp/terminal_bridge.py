"""Connection-scoped raw PTY bridges for persistent shells.

The public persistent-shell tools intentionally remain snapshot based. This
module is an internal Human UI transport. POSIX bridges start a short-lived
``tmux attach-session`` client; Windows bridges subscribe to the existing
ConPTY session's shared reader. Closing either bridge removes only the raw
client and preserves the underlying persistent shell.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import errno
import os
import re
import secrets
import select
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import conpty
from .config.settings import get_settings
from .ops.shell import (
    PERSISTENT_SHELL_MAX_COLUMNS,
    PERSISTENT_SHELL_MAX_ROWS,
    PERSISTENT_SHELL_MIN_COLUMNS,
    PERSISTENT_SHELL_MIN_ROWS,
)
from .tmux_helper import require_tmux

TERMINAL_BRIDGE_MAX_CHUNK_BYTES = 65_536
TERMINAL_BRIDGE_MAX_WAIT_MS = 1_000
TERMINAL_BRIDGE_BACKEND = "tmux-pty"
TERMINAL_BRIDGE_BACKENDS = frozenset(
    {TERMINAL_BRIDGE_BACKEND, conpty.CONPTY_BACKEND}
)
_TERMINAL_BRIDGE_HARD_IDLE_TIMEOUT_S = 300
_BRIDGE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
_SHELL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class TerminalBridgeError(RuntimeError):
    """Base class for internal raw-terminal bridge failures."""


class TerminalBridgeUnsupportedError(TerminalBridgeError):
    """Raised when the current platform cannot create a raw PTY bridge."""


class TerminalBridgeBusyError(TerminalBridgeError):
    """Raised when a shell already has an exclusive Human UI raw attachment."""


class TerminalBridgeNotFoundError(TerminalBridgeError):
    """Raised when a bridge capability is unknown, expired, or already closed."""


def _bounded_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
    label: str,
) -> int:
    if value is None or value == "":
        normalized = default
    else:
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be an integer") from exc
    if not minimum <= normalized <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return normalized


def _shell_id(value: Any) -> str:
    normalized = str(value or "")
    if not _SHELL_ID_PATTERN.fullmatch(normalized):
        raise ValueError(
            "shell_id must be 1-64 characters using letters, digits, '.', '_' or '-'"
        )
    return normalized


def _bridge_id(value: Any) -> str:
    normalized = str(value or "")
    if not _BRIDGE_ID_PATTERN.fullmatch(normalized):
        raise TerminalBridgeNotFoundError("Terminal bridge is unavailable")
    return normalized


def _terminal_size(cols: Any, rows: Any) -> tuple[int, int]:
    columns = _bounded_int(
        cols,
        default=120,
        minimum=PERSISTENT_SHELL_MIN_COLUMNS,
        maximum=PERSISTENT_SHELL_MAX_COLUMNS,
        label="cols",
    )
    lines = _bounded_int(
        rows,
        default=36,
        minimum=PERSISTENT_SHELL_MIN_ROWS,
        maximum=PERSISTENT_SHELL_MAX_ROWS,
        label="rows",
    )
    return columns, lines


def _decode_chunk(value: Any) -> bytes:
    encoded = str(value or "")
    if len(encoded) > ((TERMINAL_BRIDGE_MAX_CHUNK_BYTES + 2) // 3) * 4 + 4:
        raise ValueError("Terminal bridge input is too large")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Terminal bridge input must be valid base64") from exc
    if len(data) > TERMINAL_BRIDGE_MAX_CHUNK_BYTES:
        raise ValueError("Terminal bridge input is too large")
    return data


def _idle_timeout_s() -> float:
    configured = int(get_settings().ui_terminal_idle_timeout_s)
    if configured <= 0:
        return float(_TERMINAL_BRIDGE_HARD_IDLE_TIMEOUT_S)
    return float(max(60, min(configured, _TERMINAL_BRIDGE_HARD_IDLE_TIMEOUT_S)))


def _use_conpty_bridge() -> bool:
    return os.name == "nt"


class _TerminalProcess(Protocol):
    backend: str
    shell_id: str

    def read_wait(self, max_bytes: int, wait_ms: int) -> tuple[bytes, bool]: ...

    def write_all(self, data: bytes) -> None: ...

    def resize(self, cols: int, rows: int) -> bool: ...

    def close_sync(self) -> None: ...


class _UnixTmuxAttach:
    """One POSIX PTY hosting a tmux attach client."""

    backend = TERMINAL_BRIDGE_BACKEND

    def __init__(self, shell_id: str, cols: int, rows: int) -> None:
        if os.name == "nt":  # pragma: no cover - exercised by platform guards.
            raise TerminalBridgeUnsupportedError(
                "Raw tmux terminal bridges require POSIX PTY support"
            )

        import fcntl
        import pty
        import struct
        import termios

        self._fcntl = fcntl
        self._struct = struct
        self._termios = termios
        self._close_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._closed = False
        self.shell_id = shell_id
        self.master_fd = -1

        tmux_bin = require_tmux().path
        assert tmux_bin is not None
        check = subprocess.run(
            [tmux_bin, "has-session", "-t", shell_id],
            capture_output=True,
            check=False,
            timeout=10,
        )
        if check.returncode != 0:
            detail = (
                (check.stderr or check.stdout)
                .decode("utf-8", errors="replace")
                .strip()
            )
            raise TerminalBridgeNotFoundError(
                detail or f"Persistent shell not found: {shell_id}"
            )

        master_fd, slave_fd = pty.openpty()
        self.master_fd = master_fd
        try:
            self.resize(cols, rows)
            env = os.environ.copy()
            env.pop("TMUX", None)
            env["TERM"] = "xterm-256color"
            env["COLORTERM"] = "truecolor"
            self.process = subprocess.Popen(
                [tmux_bin, "attach-session", "-t", shell_id],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=env,
                close_fds=True,
                start_new_session=True,
                bufsize=0,
            )
        except Exception:
            with contextlib.suppress(OSError):
                os.close(master_fd)
            raise
        finally:
            with contextlib.suppress(OSError):
                os.close(slave_fd)
        os.set_blocking(master_fd, False)

    def resize(self, cols: int, rows: int) -> bool:
        if self._closed or self.master_fd < 0:
            raise TerminalBridgeNotFoundError("Terminal bridge is unavailable")
        winsize = self._struct.pack("HHHH", rows, cols, 0, 0)
        self._fcntl.ioctl(
            self.master_fd,
            self._termios.TIOCSWINSZ,
            winsize,
        )
        process = getattr(self, "process", None)
        if process is not None and process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGWINCH)
        return True

    def read_wait(self, max_bytes: int, wait_ms: int) -> tuple[bytes, bool]:
        if self._closed or self.master_fd < 0:
            return b"", True
        timeout = max(0.0, wait_ms / 1000.0)
        readable, _, _ = select.select([self.master_fd], [], [], timeout)
        if not readable:
            return b"", self.process.poll() is not None
        try:
            data = os.read(self.master_fd, max_bytes)
        except BlockingIOError:
            return b"", self.process.poll() is not None
        except OSError as exc:
            if exc.errno in {errno.EIO, errno.EBADF}:
                return b"", True
            raise
        return data, not data

    def _write_all(self, data: bytes) -> None:
        if (
            self._closed
            or self.master_fd < 0
            or self.process.poll() is not None
        ):
            raise TerminalBridgeNotFoundError("Terminal bridge is unavailable")
        remaining = memoryview(data)
        with self._write_lock:
            while remaining:
                try:
                    written = os.write(self.master_fd, remaining)
                except BlockingIOError:
                    select.select([], [self.master_fd], [], 0.1)
                    continue
                except OSError as exc:
                    if exc.errno in {errno.EIO, errno.EBADF}:
                        raise TerminalBridgeNotFoundError(
                            "Terminal bridge is unavailable"
                        ) from exc
                    raise
                if written <= 0:
                    raise OSError("PTY write made no progress")
                remaining = remaining[written:]

    def write_all(self, data: bytes) -> None:
        if data:
            self._write_all(data)

    def close_sync(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            master_fd = self.master_fd
            self.master_fd = -1
            process = getattr(self, "process", None)

        if master_fd >= 0:
            with contextlib.suppress(OSError):
                os.close(master_fd)
        if process is None or process.poll() is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=2)


@dataclass
class _Bridge:
    bridge_id: str
    shell_id: str
    process: _TerminalProcess
    cols: int
    rows: int
    idle_timeout_s: float
    last_activity: float = field(default_factory=time.monotonic)
    timer: threading.Timer | None = None


_BRIDGES: dict[str, _Bridge] = {}
_SHELL_BRIDGES: dict[str, str] = {}
_PENDING_SHELLS: set[str] = set()
_BRIDGES_LOCK = threading.Lock()


def _schedule_expiry_locked(
    bridge: _Bridge, delay: float | None = None
) -> None:
    timer = threading.Timer(
        max(1.0, delay if delay is not None else bridge.idle_timeout_s),
        _expire_bridge,
        args=(bridge.bridge_id,),
    )
    timer.daemon = True
    bridge.timer = timer
    timer.start()


def _expire_bridge(bridge_id: str) -> None:
    process: _TerminalProcess | None = None
    with _BRIDGES_LOCK:
        bridge = _BRIDGES.get(bridge_id)
        if bridge is None:
            return
        remaining = bridge.idle_timeout_s - (
            time.monotonic() - bridge.last_activity
        )
        if remaining > 0:
            _schedule_expiry_locked(bridge, remaining)
            return
        _BRIDGES.pop(bridge_id, None)
        if _SHELL_BRIDGES.get(bridge.shell_id) == bridge_id:
            _SHELL_BRIDGES.pop(bridge.shell_id, None)
        process = bridge.process
        bridge.timer = None
    if process is not None:
        process.close_sync()


def _lookup_bridge(bridge_id: Any, *, touch: bool = True) -> _Bridge:
    normalized = _bridge_id(bridge_id)
    with _BRIDGES_LOCK:
        bridge = _BRIDGES.get(normalized)
        if bridge is None:
            raise TerminalBridgeNotFoundError("Terminal bridge is unavailable")
        if touch:
            bridge.last_activity = time.monotonic()
        return bridge


def _detach_bridge(bridge_id: Any) -> _Bridge | None:
    normalized = _bridge_id(bridge_id)
    with _BRIDGES_LOCK:
        bridge = _BRIDGES.pop(normalized, None)
        if bridge is None:
            return None
        if _SHELL_BRIDGES.get(bridge.shell_id) == normalized:
            _SHELL_BRIDGES.pop(bridge.shell_id, None)
        if bridge.timer is not None:
            bridge.timer.cancel()
            bridge.timer = None
        return bridge


async def open_terminal_bridge_execute(
    shell_id: str,
    cols: int = 120,
    rows: int = 36,
) -> dict[str, Any]:
    """Open one exclusive raw PTY attachment to a persistent shell."""
    normalized_shell = _shell_id(shell_id)
    columns, lines = _terminal_size(cols, rows)

    maximum = max(1, min(int(get_settings().ui_terminal_max_connections), 128))
    with _BRIDGES_LOCK:
        if (
            normalized_shell in _SHELL_BRIDGES
            or normalized_shell in _PENDING_SHELLS
        ):
            raise TerminalBridgeBusyError(
                f"Persistent shell {normalized_shell} already has a raw terminal client"
            )
        if len(_BRIDGES) + len(_PENDING_SHELLS) >= maximum:
            raise TerminalBridgeBusyError(
                "Too many active raw terminal bridges"
            )
        _PENDING_SHELLS.add(normalized_shell)

    bridge_id = secrets.token_urlsafe(32)
    process: _TerminalProcess | None = None
    try:
        if _use_conpty_bridge():
            if not conpty.is_available():
                raise TerminalBridgeUnsupportedError(
                    "Raw terminal bridges on Windows require pywinpty"
                )
            try:
                process = await asyncio.to_thread(
                    conpty.open_raw_attachment,
                    normalized_shell,
                    bridge_id,
                    columns,
                    lines,
                )
            except RuntimeError as exc:
                raise TerminalBridgeNotFoundError(str(exc)) from exc
        else:
            process = await asyncio.to_thread(
                _UnixTmuxAttach,
                normalized_shell,
                columns,
                lines,
            )
        bridge = _Bridge(
            bridge_id=bridge_id,
            shell_id=normalized_shell,
            process=process,
            cols=columns,
            rows=lines,
            idle_timeout_s=_idle_timeout_s(),
        )
        with _BRIDGES_LOCK:
            _PENDING_SHELLS.discard(normalized_shell)
            if normalized_shell in _SHELL_BRIDGES:
                raise TerminalBridgeBusyError(
                    f"Persistent shell {normalized_shell} already has a raw terminal client"
                )
            _BRIDGES[bridge_id] = bridge
            _SHELL_BRIDGES[normalized_shell] = bridge_id
            _schedule_expiry_locked(bridge)
        process = None
        return {
            "bridge_id": bridge_id,
            "shell_id": normalized_shell,
            "cols": columns,
            "rows": lines,
            "backend": bridge.process.backend,
        }
    finally:
        with _BRIDGES_LOCK:
            _PENDING_SHELLS.discard(normalized_shell)
        if process is not None:
            await asyncio.to_thread(process.close_sync)


async def read_terminal_bridge_execute(
    bridge_id: str,
    max_bytes: int = TERMINAL_BRIDGE_MAX_CHUNK_BYTES,
    wait_ms: int = 250,
) -> dict[str, Any]:
    """Read one bounded raw byte chunk from a terminal bridge."""
    limit = _bounded_int(
        max_bytes,
        default=TERMINAL_BRIDGE_MAX_CHUNK_BYTES,
        minimum=1,
        maximum=TERMINAL_BRIDGE_MAX_CHUNK_BYTES,
        label="max_bytes",
    )
    wait = _bounded_int(
        wait_ms,
        default=250,
        minimum=0,
        maximum=TERMINAL_BRIDGE_MAX_WAIT_MS,
        label="wait_ms",
    )
    bridge = _lookup_bridge(bridge_id)
    data, eof = await asyncio.to_thread(bridge.process.read_wait, limit, wait)
    if len(data) > limit:
        raise TerminalBridgeError("Terminal bridge returned an oversized chunk")
    if eof:
        detached = _detach_bridge(bridge.bridge_id)
        if detached is not None:
            await asyncio.to_thread(detached.process.close_sync)
    return {
        "bridge_id": bridge.bridge_id,
        "data_b64": base64.b64encode(data).decode("ascii"),
        "bytes": len(data),
        "eof": bool(eof),
    }


async def write_terminal_bridge_execute(
    bridge_id: str,
    data_b64: str,
) -> dict[str, Any]:
    """Write one bounded raw byte chunk to a terminal bridge in order."""
    data = _decode_chunk(data_b64)
    bridge = _lookup_bridge(bridge_id)
    await asyncio.to_thread(bridge.process.write_all, data)
    return {
        "bridge_id": bridge.bridge_id,
        "written_bytes": len(data),
    }


async def resize_terminal_bridge_execute(
    bridge_id: str,
    cols: int,
    rows: int,
) -> dict[str, Any]:
    """Resize the PTY used by one raw terminal attachment."""
    columns, lines = _terminal_size(cols, rows)
    bridge = _lookup_bridge(bridge_id)
    resized = await asyncio.to_thread(
        bridge.process.resize,
        columns,
        lines,
    )
    with _BRIDGES_LOCK:
        current = _BRIDGES.get(bridge.bridge_id)
        if current is not None:
            current.cols = columns
            current.rows = lines
            current.last_activity = time.monotonic()
    return {
        "bridge_id": bridge.bridge_id,
        "cols": columns,
        "rows": lines,
        "resized": bool(resized),
        "backend": bridge.process.backend,
    }


async def close_terminal_bridge_execute(bridge_id: str) -> dict[str, Any]:
    """Close a raw client without terminating its persistent shell."""
    normalized = _bridge_id(bridge_id)
    bridge = _detach_bridge(normalized)
    if bridge is None:
        return {"bridge_id": normalized, "closed": False}
    await asyncio.to_thread(bridge.process.close_sync)
    return {"bridge_id": normalized, "closed": True}


def reset_terminal_bridges_for_tests() -> None:
    """Synchronously close every bridge; intended only for test isolation."""
    with _BRIDGES_LOCK:
        bridges = list(_BRIDGES.values())
        _BRIDGES.clear()
        _SHELL_BRIDGES.clear()
        _PENDING_SHELLS.clear()
        for bridge in bridges:
            if bridge.timer is not None:
                bridge.timer.cancel()
                bridge.timer = None
    for bridge in bridges:
        bridge.process.close_sync()
