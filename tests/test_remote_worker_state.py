from __future__ import annotations

from pathlib import Path

import pytest

from local_shell_mcp.remote_worker import state


def _clear_state_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)


def test_worker_state_dir_prefers_explicit_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "configured"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(configured))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))

    assert state.worker_state_dir() == configured


def test_worker_state_dir_uses_xdg_state_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_state_environment(monkeypatch)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))

    assert (
        state.worker_state_dir() == tmp_path / "xdg" / "local-shell-mcp-worker"
    )


def test_worker_state_dir_uses_home_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_state_environment(monkeypatch)
    monkeypatch.setattr(state.Path, "home", classmethod(lambda _cls: tmp_path))

    assert state.worker_state_dir() == (
        tmp_path / ".local" / "state" / "local-shell-mcp-worker"
    )


def test_worker_state_paths_share_one_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))

    assert state.worker_runtime_dir() == tmp_path / "runtime"
    assert state.runtime_metadata_path() == tmp_path / "runtime.json"
    assert state.worker_lock_path() == tmp_path / "worker.lock"
