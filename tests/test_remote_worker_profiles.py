import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import workgate.remote_worker.cli as worker_cli
import workgate.remote_worker.profile_launcher as profile_launcher
import workgate.remote_worker.profiles as worker_profiles
import workgate.remote_worker.worker as worker
from workgate.remote_worker.state import (
    WORKER_DATA_DIR_ENV,
    WORKER_PROFILE_ID_ENV,
    WORKER_RUNTIME_DIGEST_ENV,
    activate_worker_profile,
    activate_worker_runtime,
    runtime_metadata_path,
    worker_launcher_path,
    worker_launcher_runner_path,
    worker_profile_metadata_path,
    worker_python_path,
    worker_runtime_dir,
)


def _clear_profile_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WORKER_PROFILE_ID_ENV, "")
    monkeypatch.setenv(WORKER_RUNTIME_DIGEST_ENV, "")
    monkeypatch.setenv("WORKGATE_WORKSPACE_ROOT", "")
    monkeypatch.setenv("WORKGATE_STATE_DIR", "")
    monkeypatch.setenv("WORKGATE_ALLOW_FULL_CONTROL", "")


def _identity(name: str, workdir: str) -> dict[str, str]:
    return {
        "server": "https://controller.test",
        "name": name,
        "access": f"access-{name}",
        "workdir": workdir,
    }


def test_profile_identities_are_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_profile_environment(monkeypatch)
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(tmp_path))
    first = "p_abcdefgh"
    second = "p_ijklmnop"

    worker._write_worker_identity(_identity("worker-a", "/work/a"), first)
    worker._write_worker_identity(_identity("worker-b", "/work/b"), second)

    assert worker.load_worker_identity(first)["name"] == "worker-a"
    assert worker.load_worker_identity(second)["name"] == "worker-b"
    assert (tmp_path / "profiles" / first / "identity.json").is_file()
    assert (tmp_path / "profiles" / second / "identity.json").is_file()
    assert not (tmp_path / "identity.json").exists()


@pytest.mark.asyncio
async def test_profile_resume_persists_canonical_renamed_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_profile_environment(monkeypatch)
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(tmp_path))
    profile_id = "p_abcdefgh"
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    digest = "a" * 64
    original = {
        **_identity("worker-old", str(workdir)),
        "profile_id": profile_id,
    }
    worker._write_worker_identity(original, profile_id)
    captured: dict[str, Any] = {}

    async def resume(
        _url: str,
        payload: dict[str, Any],
        _headers: dict[str, str],
        _timeout: int,
        selected_profile: str,
    ) -> dict[str, Any]:
        captured.update(payload=payload, profile_id=selected_profile)
        return {"ok": True, "data": {"name": "worker-renamed"}}

    monkeypatch.setattr(worker, "_worker_resume_or_none", resume)
    monkeypatch.setattr(worker, "worker_capabilities", lambda: [])
    monkeypatch.setattr(
        worker,
        "worker_info",
        lambda _workdir, _profile_id=None: {},
    )
    monkeypatch.setattr(
        worker.worker_runtime,
        "current_runtime_identity",
        lambda: {"sha256": digest, "bundle_version": "4.0.0"},
    )

    stored, data = await worker._enroll_or_resume_worker(
        "https://controller.test",
        "",
        "worker-old",
        str(workdir),
        profile_id,
    )

    assert captured["profile_id"] == profile_id
    assert captured["payload"]["name"] == "worker-old"
    assert data["name"] == "worker-renamed"
    assert stored == {
        "server": "https://controller.test",
        "name": "worker-renamed",
        "access": "access-worker-old",
        "workdir": str(workdir),
        "profile_id": profile_id,
    }
    assert worker.load_worker_identity(profile_id) == stored
    profile = worker_profiles.read_worker_profile(profile_id)
    assert profile["name"] == "worker-renamed"
    assert profile["runtime_sha256"] == digest


@pytest.mark.asyncio
async def test_run_worker_locked_does_not_rewrite_enrollment_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_id = "p_abcdefgh"
    identity = {
        **_identity("worker-renamed", str(tmp_path)),
        "profile_id": profile_id,
    }

    async def enroll_or_resume(*_args: Any, **_kwargs: Any):
        return identity, {
            "upgrade": {
                "required": True,
                "version": "4.1.0",
                "sha256": "b" * 64,
                "manifest_path": "/remote/worker-bundle.tgz?manifest=1",
            }
        }

    async def reexec(*_args: Any, **_kwargs: Any) -> None:
        raise SystemExit(0)

    monkeypatch.setattr(worker, "_enroll_or_resume_worker", enroll_or_resume)
    monkeypatch.setattr(worker, "_install_and_reexec_worker", reexec)
    monkeypatch.setattr(
        worker,
        "_write_worker_identity",
        lambda *_args, **_kwargs: pytest.fail(
            "run loop rewrote the identity already persisted during enrollment"
        ),
    )

    with pytest.raises(SystemExit):
        await worker._run_worker_locked(
            "https://controller.test",
            "",
            "worker-renamed",
            str(tmp_path),
            profile_id,
        )


def test_active_profile_survives_credential_free_reexec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_profile_environment(monkeypatch)
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(tmp_path))
    profile_id = "p_abcdefgh"
    identity = _identity("worker-a", "/work/a")

    worker._write_worker_identity(identity, profile_id)
    monkeypatch.setenv(WORKER_PROFILE_ID_ENV, profile_id)

    assert activate_worker_profile(profile_id) == profile_id
    assert os.environ[WORKER_PROFILE_ID_ENV] == profile_id
    assert worker.load_worker_identity() == identity


def test_profile_runtime_state_is_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_profile_environment(monkeypatch)
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(tmp_path))
    profile_id = "p_abcdefgh"
    workdir = str(tmp_path / "workspace")

    worker._configure_worker_runtime_env(workdir, profile_id)

    assert os.environ["WORKGATE_WORKSPACE_ROOT"] == workdir
    assert os.environ["WORKGATE_STATE_DIR"] == str(
        tmp_path / "profiles" / profile_id / "state"
    )


def test_reconnect_command_is_credential_free_and_shell_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "worker state"
    data_dir = tmp_path / "worker data"
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(state_dir))
    monkeypatch.setenv(WORKER_DATA_DIR_ENV, str(data_dir))

    command = worker.worker_reconnect_command("p_abcdefgh")

    assert shlex.split(command) == [str(worker_launcher_path()), "p_abcdefgh"]
    assert "access" not in command
    assert "invite" not in command


def test_profile_launcher_materialization_is_stable_and_runtime_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "worker state"
    data_dir = tmp_path / "worker data"
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(state_dir))
    monkeypatch.setenv(WORKER_DATA_DIR_ENV, str(data_dir))

    launcher, changed = profile_launcher.ensure_profile_launcher(sys.executable)
    runner = worker_launcher_runner_path().read_text(encoding="utf-8")

    assert changed is True
    assert launcher == worker_launcher_path()
    assert worker_python_path().read_text(encoding="utf-8").strip() == str(
        Path(sys.executable).resolve()
    )
    assert "WORKGATE_WORKER_STATE_DIR" in runner
    assert WORKER_DATA_DIR_ENV in runner
    assert 'environment["PYTHONPATH"] = str(runtime)' in runner
    assert "os.execve(" in runner
    assert "remote_worker.compat" not in runner
    if os.name != "nt":
        assert launcher.stat().st_mode & 0o777 == 0o700

    same_launcher, changed_again = profile_launcher.ensure_profile_launcher(
        sys.executable
    )

    assert same_launcher == launcher
    assert changed_again is False


def test_profile_launcher_reconnect_command_validates_profile_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(WORKER_DATA_DIR_ENV, str(tmp_path / "worker data"))

    command = profile_launcher.profile_reconnect_command("p_abcdefgh")
    if os.name == "nt":
        assert command == subprocess.list2cmdline(
            [str(worker_launcher_path()), "p_abcdefgh"]
        )
    else:
        assert shlex.split(command) == [
            str(worker_launcher_path()),
            "p_abcdefgh",
        ]

    with pytest.raises(ValueError, match="profile id"):
        profile_launcher.profile_reconnect_command("bad")


def test_reconnect_command_formatter_uses_windows_cmd_quoting() -> None:
    argv = [r"C:\Users\Worker Name\state\run.cmd", "p_abcdefgh"]

    assert worker._format_reconnect_command(argv, windows=True) == (
        subprocess.list2cmdline(argv)
    )
    assert worker._format_reconnect_command(argv, windows=False) == (
        shlex.join(argv)
    )


def test_worker_info_reports_profile_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(tmp_path))

    info = worker.worker_info("/work/a", "p_abcdefgh")

    assert info["profile_id"] == "p_abcdefgh"
    assert info["launcher_path"] == str(worker_launcher_path())


def test_active_runtime_selects_content_addressed_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_profile_environment(monkeypatch)
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(tmp_path))
    digest = "a" * 64
    monkeypatch.setenv(WORKER_RUNTIME_DIGEST_ENV, digest)

    assert activate_worker_runtime(digest) == digest
    assert worker_runtime_dir() == tmp_path / "runtimes" / digest
    assert runtime_metadata_path() == (
        tmp_path / "runtimes" / digest / "runtime.json"
    )


def test_profile_metadata_is_atomic_validated_and_credential_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(tmp_path))
    profile_id = "p_abcdefgh"
    digest = "a" * 64

    stored = worker_profiles.update_worker_profile(
        profile_id,
        runtime_sha256=digest,
        runtime_version="3.9.1",
        server="https://controller.test",
        name="worker-a",
        workdir="/work/a",
    )

    assert worker_profiles.read_worker_profile(profile_id) == stored
    encoded = (tmp_path / "profiles" / profile_id / "profile.json").read_text(
        encoding="utf-8"
    )
    assert "access" not in encoded
    assert "invite" not in encoded
    assert "token" not in encoded


@pytest.mark.parametrize(
    ("digest", "name"),
    [("bad", "worker-a"), ("a" * 64, "worker\nname")],
)
def test_profile_metadata_rejects_invalid_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    digest: str,
    name: str,
) -> None:
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(tmp_path))

    with pytest.raises(ValueError, match="runtime|control"):
        worker_profiles.update_worker_profile(
            "p_abcdefgh",
            runtime_sha256=digest,
            name=name,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("server", 123, "must be a string"),
        ("name", "x" * 513, "is too large"),
    ],
)
def test_profile_metadata_rejects_invalid_text_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(tmp_path))
    data: dict[str, Any] = {
        "schema_version": 1,
        "profile_id": "p_abcdefgh",
        "runtime_sha256": "a" * 64,
        "runtime_version": "4.0.0",
        "server": "https://controller.test",
        "name": "worker-a",
        "workdir": "/work/a",
    }
    data[field] = value

    with pytest.raises(ValueError, match=message):
        worker_profiles.write_worker_profile("p_abcdefgh", data)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"schema_version": 999}, "unsupported"),
        (
            {
                "schema_version": 1,
                "profile_id": "p_other123",
                "runtime_sha256": "a" * 64,
            },
            "does not match",
        ),
        (
            {
                "schema_version": 1,
                "profile_id": "p_abcdefgh",
                "runtime_sha256": 123,
            },
            "must be a string",
        ),
        ([], "must be a JSON object"),
    ],
)
def test_profile_reader_rejects_invalid_documents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
    message: str,
) -> None:
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(tmp_path))
    path = worker_profile_metadata_path("p_abcdefgh")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        worker_profiles.read_worker_profile("p_abcdefgh")


def test_profile_reader_rejects_unreadable_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(tmp_path))
    path = worker_profile_metadata_path("p_abcdefgh")
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match="is unreadable"):
        worker_profiles.read_worker_profile("p_abcdefgh")


@pytest.mark.asyncio
async def test_required_upgrade_switches_profile_runtime_before_reexec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_profile_environment(monkeypatch)
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(tmp_path))
    profile_id = "p_abcdefgh"
    old_digest = "a" * 64
    new_digest = "b" * 64
    worker._write_worker_identity(_identity("worker-a", "/work/a"), profile_id)
    monkeypatch.setenv(WORKER_PROFILE_ID_ENV, profile_id)
    monkeypatch.setenv(WORKER_RUNTIME_DIGEST_ENV, old_digest)

    monkeypatch.setattr(
        worker.worker_runtime,
        "install_runtime",
        lambda *_args, **_kwargs: {
            "updated": True,
            "sha256": new_digest,
            "version": "3.9.2",
            "runtime": str(tmp_path / "runtimes" / new_digest),
        },
    )
    monkeypatch.setattr(
        worker.worker_runtime,
        "reexec_worker",
        lambda: (_ for _ in ()).throw(SystemExit(0)),
    )

    with pytest.raises(SystemExit):
        await worker._install_and_reexec_worker(
            {
                "version": "3.9.2",
                "sha256": new_digest,
                "manifest_path": "/remote/worker-bundle.tgz?manifest=1",
            },
            server="https://controller.test",
            worker_version="3.9.1",
        )

    assert os.environ[WORKER_RUNTIME_DIGEST_ENV] == new_digest
    profile = worker_profiles.read_worker_profile(profile_id)
    assert profile["runtime_sha256"] == new_digest
    assert profile["runtime_version"] == "3.9.2"
    assert profile["server"] == "https://controller.test"
    assert profile["name"] == "worker-a"
    assert profile["workdir"] == "/work/a"


@pytest.mark.asyncio
async def test_required_upgrade_refreshes_managed_service_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workgate.remote_worker.service as worker_service

    _clear_profile_environment(monkeypatch)
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("WORKGATE_WORKER_MANAGED", "1")
    new_digest = "b" * 64
    monkeypatch.setattr(
        worker.worker_runtime,
        "install_runtime",
        lambda *_args, **_kwargs: {
            "updated": True,
            "sha256": new_digest,
            "version": "3.9.2",
            "runtime": str(tmp_path / "runtimes" / new_digest),
        },
    )
    refreshed: list[tuple[str | None, str | None]] = []
    monkeypatch.setattr(
        worker_service,
        "ensure_launcher",
        lambda digest=None, profile_id=None: (
            refreshed.append((digest, profile_id)) or tmp_path / "launcher",
            True,
        ),
    )
    monkeypatch.setattr(
        worker.worker_runtime,
        "reexec_worker",
        lambda: (_ for _ in ()).throw(SystemExit(0)),
    )

    with pytest.raises(SystemExit):
        await worker._install_and_reexec_worker(
            {
                "version": "3.9.2",
                "sha256": new_digest,
                "manifest_path": "/remote/worker-bundle.tgz?manifest=1",
            },
            server="https://controller.test",
            worker_version="3.9.1",
        )

    assert refreshed == [(new_digest, None)]
    assert os.environ[WORKER_RUNTIME_DIGEST_ENV] == new_digest


@pytest.mark.asyncio
async def test_required_upgrade_preserves_managed_profile_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workgate.remote_worker.service as worker_service

    _clear_profile_environment(monkeypatch)
    monkeypatch.setenv("WORKGATE_WORKER_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("WORKGATE_WORKER_MANAGED", "1")
    profile_id = "p_abcdefgh"
    activate_worker_profile(profile_id)
    worker._write_worker_identity(_identity("worker-a", "/work/a"), profile_id)
    new_digest = "c" * 64
    monkeypatch.setattr(
        worker.worker_runtime,
        "install_runtime",
        lambda *_args, **_kwargs: {
            "updated": True,
            "sha256": new_digest,
            "version": "3.9.2",
            "runtime": str(tmp_path / "runtimes" / new_digest),
        },
    )
    refreshed: list[tuple[str | None, str | None]] = []
    monkeypatch.setattr(
        worker_service,
        "ensure_launcher",
        lambda digest=None, selected_profile=None: (
            refreshed.append((digest, selected_profile))
            or tmp_path / "launcher",
            True,
        ),
    )
    monkeypatch.setattr(
        worker.worker_runtime,
        "reexec_worker",
        lambda: (_ for _ in ()).throw(SystemExit(0)),
    )

    with pytest.raises(SystemExit):
        await worker._install_and_reexec_worker(
            {
                "version": "3.9.2",
                "sha256": new_digest,
                "manifest_path": "/remote/worker-bundle.tgz?manifest=1",
            },
            server="https://controller.test",
            worker_version="3.9.1",
        )

    assert refreshed == [(new_digest, profile_id)]
    assert (
        worker_profiles.read_worker_profile(profile_id)["runtime_sha256"]
        == new_digest
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    worker_cli.add_worker_subcommands(parser)
    return parser


def test_connect_cli_passes_explicit_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, ...]] = []

    async def run(*args: Any) -> None:
        calls.append(args)

    monkeypatch.setattr(worker, "run_worker", run)
    args = _parser().parse_args(
        [
            "connect",
            "--server",
            "https://controller.test",
            "--invite",
            "invite",
            "--profile",
            "p_abcdefgh",
        ]
    )

    args.handler(args)

    assert calls == [
        ("https://controller.test", "invite", None, None, "p_abcdefgh")
    ]


def test_run_cli_selects_stored_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str | None] = []

    async def run(profile_id: str | None = None) -> None:
        calls.append(profile_id)

    monkeypatch.setattr(worker, "run_stored_worker", run)
    monkeypatch.setattr(
        "workgate.remote_worker.service.prepare_worker_service_environment",
        lambda: None,
    )
    args = _parser().parse_args(["run", "p_abcdefgh"])

    args.handler(args)

    assert calls == ["p_abcdefgh"]
