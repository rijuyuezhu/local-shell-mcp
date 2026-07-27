import argparse
import os
import shlex
from pathlib import Path
from typing import Any

import pytest

import local_shell_mcp.remote_worker.cli as worker_cli
import local_shell_mcp.remote_worker.profiles as worker_profiles
import local_shell_mcp.remote_worker.worker as worker
from local_shell_mcp.remote_worker.state import (
    WORKER_PROFILE_ID_ENV,
    WORKER_RUNTIME_DIGEST_ENV,
    activate_worker_profile,
    activate_worker_runtime,
    runtime_metadata_path,
    worker_runtime_dir,
)


def _clear_profile_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WORKER_PROFILE_ID_ENV, "")
    monkeypatch.setenv(WORKER_RUNTIME_DIGEST_ENV, "")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", "")
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", "")
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL", "")


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
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
    first = "p_abcdefgh"
    second = "p_ijklmnop"

    worker._write_worker_identity(_identity("worker-a", "/work/a"), first)
    worker._write_worker_identity(_identity("worker-b", "/work/b"), second)

    assert worker.load_worker_identity(first)["name"] == "worker-a"
    assert worker.load_worker_identity(second)["name"] == "worker-b"
    assert (tmp_path / "profiles" / first / "identity.json").is_file()
    assert (tmp_path / "profiles" / second / "identity.json").is_file()
    assert not (tmp_path / "identity.json").exists()


def test_active_profile_survives_credential_free_reexec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_profile_environment(monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
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
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
    profile_id = "p_abcdefgh"
    workdir = str(tmp_path / "workspace")

    worker._configure_worker_runtime_env(workdir, profile_id)

    assert os.environ["LOCAL_SHELL_MCP_WORKSPACE_ROOT"] == workdir
    assert os.environ["LOCAL_SHELL_MCP_STATE_DIR"] == str(
        tmp_path / "profiles" / profile_id / "state"
    )


def test_reconnect_command_is_credential_free_and_shell_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "worker state"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(state_dir))

    command = worker.worker_reconnect_command("p_abcdefgh")

    assert shlex.split(command) == [str(state_dir / "run"), "p_abcdefgh"]
    assert "access" not in command
    assert "invite" not in command


def test_worker_info_reports_profile_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))

    info = worker.worker_info("/work/a", "p_abcdefgh")

    assert info["profile_id"] == "p_abcdefgh"
    assert info["launcher_path"] == str(tmp_path / "run")


def test_active_runtime_selects_content_addressed_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_profile_environment(monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
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
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
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
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))

    with pytest.raises(ValueError, match="runtime|control"):
        worker_profiles.update_worker_profile(
            "p_abcdefgh",
            runtime_sha256=digest,
            name=name,
        )


@pytest.mark.asyncio
async def test_required_upgrade_switches_profile_runtime_before_reexec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_profile_environment(monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
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
    import local_shell_mcp.remote_worker.service as worker_service

    _clear_profile_environment(monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_MANAGED", "1")
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
    refreshed: list[str | None] = []
    monkeypatch.setattr(
        worker_service,
        "ensure_launcher",
        lambda digest=None: (
            refreshed.append(digest) or tmp_path / "launcher",
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

    assert refreshed == [new_digest]
    assert os.environ[WORKER_RUNTIME_DIGEST_ENV] == new_digest


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
        "local_shell_mcp.remote_worker.service.prepare_worker_service_environment",
        lambda: None,
    )
    args = _parser().parse_args(["run", "p_abcdefgh"])

    args.handler(args)

    assert calls == ["p_abcdefgh"]
