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
