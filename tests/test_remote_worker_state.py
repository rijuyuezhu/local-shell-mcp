from pathlib import Path

import pytest

from workgate.remote_worker import state


def _clear_state_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORKGATE_WORKER_STATE_DIR", raising=False)
    monkeypatch.delenv("WORKGATE_WORKER_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)


def test_worker_state_dir_prefers_explicit_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "configured"
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(configured))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))

    assert state.worker_state_dir() == configured


def test_worker_state_dir_resolves_relative_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", "worker-state")

    expected = tmp_path / "worker-state"
    assert state.worker_state_dir() == expected
    assert state.worker_launcher_path().parent == expected
    assert state.worker_launcher_path().is_absolute()


def test_worker_state_dir_uses_xdg_state_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_state_environment(monkeypatch)
    monkeypatch.setattr(state.sys, "platform", "linux")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))

    assert state.worker_state_dir() == tmp_path / "xdg" / "workgate" / "worker"


def test_worker_xdg_roots_must_be_raw_absolute_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_state_environment(monkeypatch)
    monkeypatch.setattr(state.sys, "platform", "linux")
    monkeypatch.setattr(state.Path, "home", classmethod(lambda _cls: tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", "~/.state-alt")
    monkeypatch.setenv("XDG_DATA_HOME", "$HOME/data-alt")

    assert state.worker_state_dir() == (
        tmp_path / ".local" / "state" / "workgate" / "worker"
    )
    assert state.worker_data_dir() == (
        tmp_path / ".local" / "share" / "workgate" / "worker"
    )


def test_worker_state_dir_uses_home_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_state_environment(monkeypatch)
    monkeypatch.setattr(state.sys, "platform", "linux")
    monkeypatch.setattr(state.Path, "home", classmethod(lambda _cls: tmp_path))

    assert state.worker_state_dir() == (
        tmp_path / ".local" / "state" / "workgate" / "worker"
    )


def test_worker_defaults_use_native_macos_namespaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_state_environment(monkeypatch)
    monkeypatch.setattr(state.sys, "platform", "darwin")
    monkeypatch.setattr(state.Path, "home", classmethod(lambda _cls: tmp_path))

    support = tmp_path / "Library" / "Application Support" / "workgate"
    assert state.worker_state_dir() == support / "state" / "worker"
    assert state.worker_data_dir() == support / "data" / "worker"


def test_worker_defaults_use_native_windows_namespaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_state_environment(monkeypatch)
    local = tmp_path / "local"
    monkeypatch.setattr(state.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(local))

    assert state.worker_state_dir() == local / "workgate" / "state" / "worker"
    assert state.worker_data_dir() == local / "workgate" / "data" / "worker"


def test_legacy_worker_state_override_also_controls_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(tmp_path))

    assert state.worker_runtime_dir() == tmp_path / "runtime"
    assert state.runtime_metadata_path() == tmp_path / "runtime.json"
    assert state.worker_lock_path() == tmp_path / "worker.lock"
    assert state.worker_profiles_dir() == tmp_path / "profiles"
    assert state.worker_runtimes_dir() == tmp_path / "runtimes"
    launcher_name = "run.cmd" if state.os.name == "nt" else "run"
    assert state.worker_launcher_path() == tmp_path / launcher_name
    assert state.worker_launcher_runner_path() == tmp_path / "run.py"
    assert state.worker_python_path() == tmp_path / "python"
    assert state.worker_install_lock_path() == tmp_path / "install.lock"


def test_worker_state_and_data_defaults_are_separate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_state_environment(monkeypatch)
    monkeypatch.setattr(state.sys, "platform", "linux")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    state_root = tmp_path / "state" / "workgate" / "worker"
    data_root = tmp_path / "data" / "workgate" / "worker"
    assert state.worker_state_dir() == state_root
    assert state.worker_data_dir() == data_root
    assert state.worker_profiles_dir() == state_root / "profiles"
    assert state.worker_runtimes_dir() == data_root / "runtimes"
    assert state.worker_install_lock_path() == data_root / "install.lock"


def test_explicit_worker_data_dir_splits_legacy_state_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_root = tmp_path / "state"
    data_root = tmp_path / "data"
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(state_root))
    monkeypatch.setenv("WORKGATE_WORKER_DATA_DIR", str(data_root))

    assert state.worker_profiles_dir() == state_root / "profiles"
    assert state.worker_runtimes_dir() == data_root / "runtimes"
    assert state.worker_launcher_runner_path() == data_root / "run.py"


def test_worker_profile_paths_are_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(tmp_path))
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
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(tmp_path))
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
