import re

import pytest

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.tool_session import store as store_module
from local_shell_mcp.tool_session.store import (
    UnknownAgentSessionError,
    get_tool_session_store,
)


def test_create_session_returns_8_character_alnum_id(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()

    session = store.create_session(workdir=".")

    assert re.fullmatch(r"[A-Za-z0-9]{8}", session.session_id)
    assert session.target == "local"
    assert session.workdir == str(tmp_path)
    assert session.machine is None
    assert session.worker_session_id is None


def test_create_session_retries_id_collisions(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    ids = iter(["aaaaaaaa", "aaaaaaaa", "bbbbbbbb"])
    monkeypatch.setattr(store_module, "generate_session_id", lambda: next(ids))

    first = store.create_session(workdir=".")
    second = store.create_session(workdir=".")

    assert first.session_id == "aaaaaaaa"
    assert second.session_id == "bbbbbbbb"


def test_require_session_rejects_unknown_session_id():
    store = get_tool_session_store()
    store.clear()

    with pytest.raises(UnknownAgentSessionError):
        store.require_session("missing1")


def test_snapshots_are_isolated_by_explicit_session(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    first = store.create_session(workdir=".")
    second = store.create_session(workdir=".")

    record = store.record_file_snapshot(
        session_id=first.session_id,
        path="a.txt",
        file_sha256="abc",
        total_lines=1,
        seen_ranges=((1, 1),),
    )

    assert store.get_snapshot(first.session_id, record.snapshot_id) == record
    assert store.get_snapshot(second.session_id, record.snapshot_id) is None


def test_change_session_workdir_updates_session_and_clears_snapshots(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(workdir="first")
    record = store.record_file_snapshot(
        session_id=session.session_id,
        path="a.txt",
        file_sha256="abc",
        total_lines=1,
        seen_ranges=((1, 1),),
    )

    updated = store.change_session_workdir(session.session_id, "second")

    assert updated.session_id == session.session_id
    assert updated.workdir == str(second_dir)
    assert updated.updated_at >= session.updated_at
    assert store.get_snapshot(session.session_id, record.snapshot_id) is None


def test_update_remote_session_workdir_clears_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    store = store_module.ToolSessionStore()
    remote = store.create_session(
        target="remote",
        workdir="/remote/first",
        machine="worker-a",
        worker_session_id="WORKER12",
    )
    snapshot = store.record_file_snapshot(
        session_id=remote.session_id,
        path="file.txt",
        file_sha256="a" * 64,
        total_lines=1,
        seen_ranges=((1, 1),),
    )

    updated = store.update_remote_session_workdir(
        remote.session_id, "/remote/second"
    )

    assert updated.workdir == "/remote/second"
    assert store.get_snapshot(remote.session_id, snapshot.snapshot_id) is None
    with pytest.raises(ValueError, match="must not be empty"):
        store.update_remote_session_workdir(remote.session_id, "")

    local = store.create_session(target="local", workdir=tmp_path)
    with pytest.raises(ValueError, match="not remote"):
        store.update_remote_session_workdir(local.session_id, "/remote")


def test_sessions_and_snapshots_survive_new_store_instance(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    first_store = store_module.ToolSessionStore()
    first_store.clear()
    session = first_store.create_session(workdir=tmp_path, label="durable")
    snapshot = first_store.record_file_snapshot(
        session_id=session.session_id,
        path="file.txt",
        file_sha256="b" * 64,
        total_lines=2,
        seen_ranges=((1, 2),),
    )

    second_store = store_module.ToolSessionStore()

    assert second_store.require_session(session.session_id) == session
    assert (
        second_store.get_snapshot(session.session_id, snapshot.snapshot_id)
        == snapshot
    )
    assert second_store.list_sessions() == [session]
    session_dir = tmp_path / ".state" / "sessions" / session.session_id
    assert (session_dir / "session.json").is_file()
    assert (session_dir / "snapshots.json").is_file()
