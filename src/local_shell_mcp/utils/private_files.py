"""Cross-platform helpers for private state files and lock files."""

from __future__ import annotations

import contextlib
import errno
import os
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO


def _ensure_lock_file(path: Path) -> None:
    """Create or repair the one-byte lock file before any process opens it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            descriptor = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
        except FileExistsError:
            try:
                if path.stat().st_size > 0:
                    return
                descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
            except FileNotFoundError, PermissionError:
                time.sleep(0.01)
                continue
        except PermissionError:
            time.sleep(0.01)
            continue
        try:
            os.write(descriptor, b"\0")
        finally:
            os.close(descriptor)
        with contextlib.suppress(OSError):
            path.chmod(0o600)
        return


def _lock_handle(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        contention_errors = {
            errno.EACCES,
            errno.EAGAIN,
            getattr(errno, "EDEADLK", errno.EACCES),
            getattr(errno, "EDEADLOCK", errno.EACCES),
        }
        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as exc:
                if exc.errno not in contention_errors:
                    raise
                time.sleep(0.01)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_handle(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def private_file_lock(path: Path) -> Generator[BinaryIO]:
    """Hold one private cross-process file lock for the context lifetime."""
    _ensure_lock_file(path)
    with path.open("r+b") as handle:
        with contextlib.suppress(OSError):
            path.chmod(0o600)
        _lock_handle(handle)
        try:
            yield handle
        finally:
            _unlock_handle(handle)


def write_private_bytes(
    path: Path, data: bytes, *, exclusive: bool = False
) -> None:
    """Write or replace one private byte file using mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT
    flags |= os.O_EXCL if exclusive else os.O_TRUNC
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
        handle.flush()
    with contextlib.suppress(OSError):
        path.chmod(0o600)


def append_private_bytes(path: Path, data: bytes) -> None:
    """Append bytes to one private file without changing existing content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "ab") as handle:
        handle.write(data)
        handle.flush()
    with contextlib.suppress(OSError):
        path.chmod(0o600)


def write_private_text(path: Path, content: str) -> None:
    """Write or replace one private UTF-8 text file."""
    write_private_bytes(path, content.encode("utf-8"))


def atomic_write_private_bytes(path: Path, data: bytes) -> None:
    """Atomically replace one private file with new bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        write_private_bytes(temporary, data, exclusive=True)
        os.replace(temporary, path)
        with contextlib.suppress(OSError):
            path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_private_text(path: Path, content: str) -> None:
    """Atomically replace one private file with UTF-8 text."""
    atomic_write_private_bytes(path, content.encode("utf-8"))
