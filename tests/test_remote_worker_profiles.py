import argparse
import os
from pathlib import Path
from typing import Any

import pytest

import local_shell_mcp.remote_worker.cli as worker_cli
import local_shell_mcp.remote_worker.worker as worker
from local_shell_mcp.remote_worker.state import (
    WORKER_PROFILE_ID_ENV,
    activate_worker_profile,
)


def _clear_profile_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(WORKER_PROFILE_ID_ENV, raising=False)
    monkeypatch.delenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("LOCAL_SHELL_MCP_STATE_DIR", raising=False)


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
