"""Cross-platform remote-worker process locking and managed handoff helpers."""

import contextlib
import errno
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Generator
from pathlib import Path
from typing import BinaryIO

from ..utils.private_files import _ensure_lock_file
from .state import worker_lock_path

_SERVICE_NAME = "local-shell-mcp-worker"
_LAUNCHD_LABEL = "com.fwerkor.local-shell-mcp-worker"
_WORKER_MANAGED_ENV = "LOCAL_SHELL_MCP_WORKER_MANAGED"
_WORKER_LOCK_INHERIT_ENV = "LOCAL_SHELL_MCP_WORKER_LOCK_HANDLE"
_WORKER_LOCK_RETRY_S = 5.0
_WORKER_LOCK_HANDOFF_RETRY_S = 0.1
_active_worker_lock_handle: BinaryIO | None = None


class WorkerAlreadyRunningError(RuntimeError):
    """Raised when a manual worker attempts to start beside an active worker."""


def _user_home() -> Path:
    configured = os.getenv("HOME") or os.getenv("USERPROFILE")
    return Path(configured).expanduser() if configured else Path.home()


def _systemd_unit_path() -> Path:
    return (
        _user_home()
        / ".config"
        / "systemd"
        / "user"
        / f"{_SERVICE_NAME}.service"
    )


def _launchd_plist_path() -> Path:
    return _user_home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )


def _user_id() -> int:
    getuid = getattr(os, "getuid", None)
    return int(getuid()) if getuid is not None else 0


def _managed_service_pid() -> int | None:
    system = platform.system()
    try:
        if (
            system == "Linux"
            and _systemd_unit_path().exists()
            and shutil.which("systemctl")
        ):
            result = _run(
                [
                    "systemctl",
                    "--user",
                    "show",
                    "--property",
                    "MainPID",
                    "--value",
                    f"{_SERVICE_NAME}.service",
                ]
            )
            value = result.stdout.strip()
            if result.returncode == 0 and value.isdigit() and int(value) > 0:
                return int(value)
        if (
            system == "Darwin"
            and _launchd_plist_path().exists()
            and shutil.which("launchctl")
        ):
            result = _run(
                ["launchctl", "print", f"gui/{_user_id()}/{_LAUNCHD_LABEL}"]
            )
            if result.returncode == 0:
                match = re.search(r"(?m)^\s*pid\s*=\s*(\d+)\s*$", result.stdout)
                if match and int(match.group(1)) > 0:
                    return int(match.group(1))
    except OSError, subprocess.SubprocessError:
        return None
    return None


def _current_worker_is_managed() -> bool:
    if os.getenv(_WORKER_MANAGED_ENV) == "1":
        return True
    return _managed_service_pid() == os.getpid()


def _lock_worker_file(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_worker_file(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _worker_lock_is_contended(exc: OSError) -> bool:
    if isinstance(exc, BlockingIOError) or exc.errno in {
        errno.EACCES,
        errno.EAGAIN,
    }:
        return True
    return os.name == "nt" and getattr(exc, "winerror", None) in {32, 33}


def prepare_worker_lock_reexec() -> int | None:
    """Mark the active worker lock handle inheritable for one process restart."""
    handle = _active_worker_lock_handle
    if handle is None:
        return None
    if os.name == "nt":
        import msvcrt

        inherited = int(msvcrt.get_osfhandle(handle.fileno()))
        os.set_handle_inheritable(inherited, True)
    else:
        inherited = handle.fileno()
        os.set_inheritable(inherited, True)
    os.environ[_WORKER_LOCK_INHERIT_ENV] = str(inherited)
    return inherited


def cancel_worker_lock_reexec(inherited: int | None) -> None:
    """Undo a prepared worker-lock inheritance after a failed restart."""
    if inherited is None:
        return
    os.environ.pop(_WORKER_LOCK_INHERIT_ENV, None)
    with contextlib.suppress(OSError):
        if os.name == "nt":
            os.set_handle_inheritable(inherited, False)
        else:
            os.set_inheritable(inherited, False)


def _adopt_worker_lock_handle() -> BinaryIO | None:
    raw_value = os.environ.pop(_WORKER_LOCK_INHERIT_ENV, "")
    if not raw_value:
        return None
    try:
        inherited = int(raw_value)
        if os.name == "nt":
            import msvcrt

            fd = msvcrt.open_osfhandle(inherited, os.O_RDWR)
        else:
            fd = inherited
            os.fstat(fd)
        return os.fdopen(fd, "r+b", buffering=0)
    except OSError, ValueError:
        return None


@contextlib.contextmanager
def worker_run_lock(profile_id: str | None = None) -> Generator[None]:
    """Hold one profile's single-instance lock across the worker lifecycle."""
    global _active_worker_lock_handle

    path = worker_lock_path(profile_id)
    _ensure_lock_file(path)
    handle = _adopt_worker_lock_handle()
    inherited = handle is not None
    windows_handoff = inherited and os.name == "nt"
    locked = inherited and not windows_handoff
    if handle is None:
        fd = os.open(path, os.O_RDWR)
        handle = os.fdopen(fd, "r+b", buffering=0)
    try:
        waiting = False
        while not locked:
            try:
                _lock_worker_file(handle)
                locked = True
            except OSError as exc:
                if not _worker_lock_is_contended(exc):
                    raise
                managed = _current_worker_is_managed()
                if not managed and not windows_handoff:
                    raise WorkerAlreadyRunningError(
                        "remote worker is already running; stop the existing "
                        "worker process before starting another"
                    ) from exc
                if managed and not waiting:
                    print(
                        "Status: another worker process is active; managed "
                        "worker is waiting for handoff...",
                        file=sys.stderr,
                        flush=True,
                    )
                    waiting = True
                time.sleep(
                    _WORKER_LOCK_HANDOFF_RETRY_S
                    if windows_handoff
                    else _WORKER_LOCK_RETRY_S
                )
        with contextlib.suppress(OSError):
            path.chmod(0o600)
        _active_worker_lock_handle = handle
        yield
    finally:
        if _active_worker_lock_handle is handle:
            _active_worker_lock_handle = None
        if locked:
            with contextlib.suppress(OSError):
                _unlock_worker_file(handle)
        handle.close()
