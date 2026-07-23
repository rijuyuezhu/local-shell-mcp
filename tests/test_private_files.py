from __future__ import annotations

import errno
import sys
from types import SimpleNamespace

import pytest

import local_shell_mcp.utils.private_files as private_files


def test_windows_file_lock_retries_contention(monkeypatch, tmp_path):
    calls: list[int] = []
    sleeps: list[float] = []

    def locking(_fd: int, mode: int, _length: int) -> None:
        calls.append(mode)
        if mode == 2 and calls.count(mode) < 3:
            raise OSError(errno.EDEADLK, "fixture contention")

    fake_msvcrt = SimpleNamespace(
        LK_NBLCK=2,
        LK_UNLCK=0,
        locking=locking,
    )
    path = tmp_path / "lock"
    with path.open("a+b") as handle:
        monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
        monkeypatch.setattr(private_files.os, "name", "nt")
        monkeypatch.setattr(private_files.time, "sleep", sleeps.append)
        private_files._lock_handle(handle)
        private_files._unlock_handle(handle)

    assert calls == [2, 2, 2, 0]
    assert sleeps == [0.01, 0.01]


def test_windows_file_lock_does_not_retry_other_errors(monkeypatch, tmp_path):
    def locking(_fd: int, _mode: int, _length: int) -> None:
        raise OSError(errno.EIO, "fixture I/O error")

    fake_msvcrt = SimpleNamespace(
        LK_NBLCK=2,
        LK_UNLCK=0,
        locking=locking,
    )
    path = tmp_path / "lock"
    with path.open("a+b") as handle:
        monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
        monkeypatch.setattr(private_files.os, "name", "nt")
        with pytest.raises(OSError, match="fixture I/O error"):
            private_files._lock_handle(handle)
