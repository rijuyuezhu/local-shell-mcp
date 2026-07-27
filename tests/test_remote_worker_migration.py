import json
import os
from pathlib import Path
from typing import Any

import pytest

import local_shell_mcp.remote_worker.identity as worker_identity
import local_shell_mcp.remote_worker.migration as worker_migration
import local_shell_mcp.remote_worker.runtime as worker_runtime
import local_shell_mcp.remote_worker.service as worker_service
import local_shell_mcp.remote_worker.worker as worker
from local_shell_mcp.remote_worker.profiles import (
    read_worker_profile,
    update_worker_profile,
)
from local_shell_mcp.remote_worker.state import (
    WORKER_PROFILE_ID_ENV,
    WORKER_RUNTIME_DIGEST_ENV,
    worker_identity_path,
    worker_launcher_path,
    worker_legacy_migration_path,
    worker_profile_identity_path,
    worker_profiles_dir,
    worker_runtime_dir_for_digest,
)


def _configure_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state_dir = tmp_path / "worker-state"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(state_dir))
    monkeypatch.setenv(WORKER_PROFILE_ID_ENV, "")
    monkeypatch.setenv(WORKER_RUNTIME_DIGEST_ENV, "")
    return state_dir


def _legacy_identity(tmp_path: Path) -> dict[str, str]:
    return {
        "server": "https://controller.test",
        "name": "legacy-edge",
        "access": "legacy-secret-access",
        "workdir": str(tmp_path / "workspace"),
    }


def _write_complete_runtime(digest: str, version: str) -> None:
    runtime_dir = worker_runtime_dir_for_digest(digest)
    for relative in worker_runtime._REQUIRED_RUNTIME_FILES:
        path = runtime_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {relative}\n", encoding="utf-8")
    worker_runtime._write_runtime_metadata(
        {
            "schema_version": 1,
            "bundle_version": version,
            "sha256": digest,
            "size": 1,
            "installed_at": 1.0,
        },
        digest,
    )


def _fake_runtime_update(
    monkeypatch: pytest.MonkeyPatch,
    *,
    digest: str = "a" * 64,
    version: str = "4.0.0",
    expected_current_version: str | None = None,
) -> list[str]:
    calls: list[str] = []

    def fake_update(
        server: str,
        *,
        force: bool = False,
        current_version: str | None = None,
    ) -> dict[str, Any]:
        assert force is False
        assert current_version == expected_current_version
        calls.append(server)
        _write_complete_runtime(digest, version)
        return {
            "updated": True,
            "sha256": digest,
            "version": version,
            "runtime": str(worker_runtime_dir_for_digest(digest)),
        }

    monkeypatch.setattr(worker_runtime, "update_installed_runtime", fake_update)
    return calls


def test_legacy_migration_is_atomic_idempotent_and_retains_old_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = _configure_state(tmp_path, monkeypatch)
    identity = _legacy_identity(tmp_path)
    worker._write_worker_identity(identity)
    legacy_runtime = state_dir / "runtime"
    legacy_runtime.mkdir(parents=True)
    (legacy_runtime / "legacy-only.txt").write_text("old", encoding="utf-8")
    calls = _fake_runtime_update(monkeypatch)

    first = worker_migration.migrate_legacy_worker_state()
    second = worker_migration.migrate_legacy_worker_state()
    inspected = worker_migration.migrated_legacy_profile()

    assert first is not None
    assert second == first
    assert inspected == first
    assert calls == [identity["server"]]
    profile_id = str(first["profile_id"])
    assert profile_id.startswith("p_")
    migrated_identity = json.loads(
        worker_profile_identity_path(profile_id).read_text(encoding="utf-8")
    )
    assert migrated_identity == {
        **identity,
        "profile_id": profile_id,
        "migration_source": "legacy-single-worker",
    }
    profile = read_worker_profile(profile_id)
    assert profile["runtime_sha256"] == "a" * 64
    assert profile["runtime_version"] == "4.0.0"
    marker = json.loads(
        worker_legacy_migration_path().read_text(encoding="utf-8")
    )
    assert marker["profile_id"] == profile_id
    assert "access" not in marker
    assert worker.load_worker_identity() == identity
    assert (legacy_runtime / "legacy-only.txt").read_text(
        encoding="utf-8"
    ) == "old"
    assert not (
        worker_runtime_dir_for_digest("a" * 64) / "legacy-only.txt"
    ).exists()
    assert worker_launcher_path().is_file()
    assert (state_dir / "run.py").is_file()
    assert (state_dir / "python").is_file()
    if os.name != "nt":
        assert worker_launcher_path().stat().st_mode & 0o111


def test_migration_rebinds_installed_legacy_service_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_state(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(worker_service, "service_manager", lambda: "systemd")
    identity = _legacy_identity(tmp_path)
    worker._write_worker_identity(identity)
    _fake_runtime_update(monkeypatch)

    unit = worker_service.systemd_unit_path()
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text("legacy enabled unit\n", encoding="utf-8")
    launcher, _changed = worker_service.ensure_launcher()
    assert 'main(["run"])' in launcher.read_text(encoding="utf-8")

    result = worker_migration.migrate_legacy_worker_state()

    assert result is not None
    profile_id = str(result["profile_id"])
    rebound = launcher.read_text(encoding="utf-8")
    assert f"runtime_digest = {'a' * 64!r}" in rebound
    assert f"os.environ[{WORKER_PROFILE_ID_ENV!r}] = {profile_id!r}" in rebound
    assert f'main(["run", "{profile_id}"])' in rebound
    assert unit.read_text(encoding="utf-8") == "legacy enabled unit\n"


def test_identity_validation_and_deletion_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_state(tmp_path, monkeypatch)
    path = worker_identity_path()
    path.parent.mkdir(parents=True)

    path.write_text("[]", encoding="utf-8")
    assert worker_identity.read_worker_identity() is None

    path.write_text(
        json.dumps({"server": "https://controller.test", "access": "x"}),
        encoding="utf-8",
    )
    assert worker_identity.read_worker_identity() is None

    path.unlink()
    with pytest.raises(ValueError, match="no stored worker identity"):
        worker_identity.load_worker_identity()

    worker_identity.write_worker_identity(
        {
            "server": "https://controller.test",
            "name": "edge-a",
            "access": "x",
            "workdir": "",
        }
    )
    with pytest.raises(ValueError, match="missing workdir"):
        worker_identity.load_worker_identity()

    worker_identity.delete_worker_identity()
    assert not path.exists()
    worker_identity.delete_worker_identity()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{", "marker is unreadable"),
        ("[]", "must be a JSON object"),
        ('{"schema_version": 999}', "unsupported legacy"),
        ('{"schema_version": 1}', "has no profile id"),
    ],
)
def test_migration_marker_validation_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    message: str,
) -> None:
    _configure_state(tmp_path, monkeypatch)
    marker = worker_legacy_migration_path()
    marker.parent.mkdir(parents=True)
    marker.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        worker_migration._read_migration_marker()


def test_interrupted_migration_reuses_complete_orphan_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_state(tmp_path, monkeypatch)
    legacy = _legacy_identity(tmp_path)
    worker._write_worker_identity(legacy)
    profile_id = "p_orphan12"
    digest = "d" * 64
    _write_complete_runtime(digest, "4.0.0")
    worker._write_worker_identity(
        {
            **legacy,
            "profile_id": profile_id,
            "migration_source": "legacy-single-worker",
        },
        profile_id,
    )
    update_worker_profile(
        profile_id,
        runtime_sha256=digest,
        runtime_version="4.0.0",
        server=legacy["server"],
        name=legacy["name"],
        workdir=legacy["workdir"],
    )

    result = worker_migration.migrate_legacy_worker_state()

    assert result is not None
    assert result["profile_id"] == profile_id
    assert (
        json.loads(worker_legacy_migration_path().read_text(encoding="utf-8"))[
            "profile_id"
        ]
        == profile_id
    )
    assert sorted(path.name for path in worker_profiles_dir().iterdir()) == [
        profile_id
    ]


def test_migration_repairs_profile_with_missing_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_state(tmp_path, monkeypatch)
    legacy = _legacy_identity(tmp_path)
    worker._write_worker_identity(legacy)
    profile_id = "p_repair123"
    worker._write_worker_identity(
        {
            **legacy,
            "profile_id": profile_id,
            "migration_source": "legacy-single-worker",
        },
        profile_id,
    )
    update_worker_profile(
        profile_id,
        runtime_sha256="e" * 64,
        runtime_version="3.9.0",
        server=legacy["server"],
        name=legacy["name"],
        workdir=legacy["workdir"],
    )
    marker = worker_legacy_migration_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"schema_version": 1, "profile_id": profile_id}),
        encoding="utf-8",
    )
    calls = _fake_runtime_update(
        monkeypatch,
        digest="f" * 64,
        version="4.1.0",
        expected_current_version="3.9.0",
    )

    result = worker_migration.migrate_legacy_worker_state()

    assert result is not None
    assert result["runtime_sha256"] == "f" * 64
    assert calls == [legacy["server"]]
    assert read_worker_profile(profile_id)["runtime_version"] == "4.1.0"


def test_migration_result_rejects_wrong_source_and_missing_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_state(tmp_path, monkeypatch)
    profile_id = "p_invalid12"
    legacy = _legacy_identity(tmp_path)
    profile = {"runtime_sha256": "1" * 64, "runtime_version": "4.0.0"}
    worker._write_worker_identity(
        {**legacy, "profile_id": profile_id}, profile_id
    )

    with pytest.raises(ValueError, match="invalid source"):
        worker_migration._migration_result(profile_id, profile)

    worker._write_worker_identity(
        {
            **legacy,
            "profile_id": profile_id,
            "migration_source": "legacy-single-worker",
        },
        profile_id,
    )
    with pytest.raises(ValueError, match="runtime is unavailable"):
        worker_migration._migration_result(profile_id, profile)


def test_marker_cannot_repair_non_migration_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_state(tmp_path, monkeypatch)
    profile_id = "p_regular12"
    identity = _legacy_identity(tmp_path)
    worker._write_worker_identity(
        {**identity, "profile_id": profile_id}, profile_id
    )
    update_worker_profile(
        profile_id,
        runtime_sha256="3" * 64,
        runtime_version="3.9.0",
        server=identity["server"],
        name=identity["name"],
        workdir=identity["workdir"],
    )
    marker = worker_legacy_migration_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"schema_version": 1, "profile_id": profile_id}),
        encoding="utf-8",
    )
    calls = _fake_runtime_update(monkeypatch, digest="4" * 64, version="4.1.0")

    with pytest.raises(ValueError, match="invalid source"):
        worker_migration.migrate_legacy_worker_state()

    assert calls == []
    profile = read_worker_profile(profile_id)
    assert profile["runtime_sha256"] == "3" * 64
    assert profile["runtime_version"] == "3.9.0"


def test_runtime_install_must_produce_complete_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_state(tmp_path, monkeypatch)
    monkeypatch.setattr(
        worker_runtime,
        "update_installed_runtime",
        lambda _server: {"sha256": "2" * 64, "version": "4.0.0"},
    )

    with pytest.raises(RuntimeError, match="runtime is incomplete"):
        worker_migration._install_current_runtime("https://controller.test")


def test_legacy_migration_failure_keeps_legacy_identity_and_no_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_state(tmp_path, monkeypatch)
    identity = _legacy_identity(tmp_path)
    worker._write_worker_identity(identity)
    _fake_runtime_update(monkeypatch)

    def fail_launcher(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("launcher unavailable")

    monkeypatch.setattr(
        worker_migration, "ensure_profile_launcher", fail_launcher
    )

    with pytest.raises(OSError, match="launcher unavailable"):
        worker_migration.migrate_legacy_worker_state()

    assert worker.load_worker_identity() == identity
    assert not worker_legacy_migration_path().exists()
    profiles = worker_profiles_dir()
    assert not profiles.exists() or not list(profiles.iterdir())


def test_legacy_migration_interrupt_removes_partial_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_state(tmp_path, monkeypatch)
    identity = _legacy_identity(tmp_path)
    worker._write_worker_identity(identity)
    _fake_runtime_update(monkeypatch)

    def interrupt_launcher(*_args: Any, **_kwargs: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(
        worker_migration, "ensure_profile_launcher", interrupt_launcher
    )

    with pytest.raises(KeyboardInterrupt):
        worker_migration.migrate_legacy_worker_state()

    assert worker.load_worker_identity() == identity
    assert not worker_legacy_migration_path().exists()
    profiles = worker_profiles_dir()
    assert not profiles.exists() or not list(profiles.iterdir())


def test_service_rebind_failure_keeps_retryable_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_state(tmp_path, monkeypatch)
    identity = _legacy_identity(tmp_path)
    worker._write_worker_identity(identity)
    _fake_runtime_update(monkeypatch)

    def fail_rebind(*_args: Any, **_kwargs: Any) -> bool:
        raise OSError("service launcher unavailable")

    monkeypatch.setattr(
        worker_service,
        "refresh_installed_service_definition",
        fail_rebind,
    )
    with pytest.raises(OSError, match="service launcher unavailable"):
        worker_migration.migrate_legacy_worker_state()

    marker = json.loads(
        worker_legacy_migration_path().read_text(encoding="utf-8")
    )
    profile_id = str(marker["profile_id"])
    assert worker_profile_identity_path(profile_id).is_file()
    rebound: list[tuple[str, str]] = []
    monkeypatch.setattr(
        worker_service,
        "refresh_installed_service_definition",
        lambda selected, digest=None: (
            rebound.append((str(selected["profile_id"]), str(digest))) or True
        ),
    )

    result = worker_migration.migrate_legacy_worker_state()

    assert result is not None
    assert result["profile_id"] == profile_id
    assert rebound == [(profile_id, "a" * 64)]


def test_legacy_migration_returns_none_without_old_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_state(tmp_path, monkeypatch)
    calls = _fake_runtime_update(monkeypatch)

    assert worker_migration.migrate_legacy_worker_state() is None
    assert calls == []
    assert not worker_legacy_migration_path().exists()


@pytest.mark.asyncio
async def test_worker_run_reexecs_into_migrated_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_state(tmp_path, monkeypatch)
    digest = "b" * 64
    profile_id = "p_abcdefgh"

    monkeypatch.setattr(
        worker_migration,
        "migrate_legacy_worker_state",
        lambda: {
            "profile_id": profile_id,
            "runtime_sha256": digest,
        },
    )

    class Restarted(RuntimeError):
        pass

    def fake_reexec() -> None:
        raise Restarted("reexec")

    monkeypatch.setattr(worker_runtime, "reexec_worker", fake_reexec)

    with pytest.raises(Restarted, match="reexec"):
        await worker.run_stored_worker()

    assert os.environ[WORKER_PROFILE_ID_ENV] == profile_id
    assert os.environ[WORKER_RUNTIME_DIGEST_ENV] == digest
