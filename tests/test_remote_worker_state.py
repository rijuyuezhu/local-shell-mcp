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
    assert state.worker_profiles_dir() == tmp_path / "profiles"
    assert state.worker_runtimes_dir() == tmp_path / "runtimes"
    launcher_name = "run.cmd" if state.os.name == "nt" else "run"
    assert state.worker_launcher_path() == tmp_path / launcher_name
    assert state.worker_launcher_runner_path() == tmp_path / "run.py"
    assert state.worker_python_path() == tmp_path / "python"
    assert (
        state.worker_legacy_migration_path() == tmp_path / "legacy-profile.json"
    )
    assert state.worker_migration_lock_path() == tmp_path / "migration.lock"
    assert state.worker_install_lock_path() == tmp_path / "install.lock"


def test_worker_profile_paths_are_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
    profile_id = "p_abcdefgh"
    profile = tmp_path / "profiles" / profile_id

    assert state.worker_profile_dir(profile_id) == profile
    assert state.worker_profile_metadata_path(profile_id) == (
        profile / "profile.json"
    )
    assert state.worker_profile_identity_path(profile_id) == (
        profile / "identity.json"
    )
    assert state.worker_profile_lock_path(profile_id) == profile / "worker.lock"


@pytest.mark.parametrize(
    "profile_id",
    ["", "worker-a", "p_short", "p_../escape", "p_abcdefgh/child"],
)
def test_worker_profile_paths_reject_unsafe_ids(profile_id: str) -> None:
    with pytest.raises(ValueError, match="profile id"):
        state.worker_profile_dir(profile_id)


def test_worker_runtime_paths_are_content_addressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
    digest = "a" * 64
    runtime = tmp_path / "runtimes" / digest

    assert state.worker_runtime_dir_for_digest(digest) == runtime
    assert state.runtime_metadata_path_for_digest(digest) == (
        runtime / "runtime.json"
    )


@pytest.mark.parametrize(
    "digest",
    ["", "a" * 63, "A" * 64, "g" * 64, "../" + "a" * 64],
)
def test_worker_runtime_paths_reject_invalid_digests(digest: str) -> None:
    with pytest.raises(ValueError, match="runtime digest"):
        state.worker_runtime_dir_for_digest(digest)
