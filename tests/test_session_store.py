import re
import time

import pytest

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.tool_session import store as store_module
from local_shell_mcp.tool_session.store import (
    SESSION_TERMINATION_PROMPT,
    ExpiredAgentSessionError,
    SessionTerminationRequestedError,
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


def test_termination_request_is_durable_idempotent_and_blocks_tool_work(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    store = store_module.ToolSessionStore()
    store.clear()
    session = store.create_session(workdir=tmp_path)

    terminated = store.request_termination(session.session_id)
    repeated = store.request_termination(session.session_id)

    assert terminated.termination_requested_at is not None
    assert (
        repeated.termination_requested_at == terminated.termination_requested_at
    )
    restored = store_module.ToolSessionStore().require_session(
        session.session_id
    )
    assert (
        restored.termination_requested_at == terminated.termination_requested_at
    )
    with pytest.raises(SessionTerminationRequestedError) as exc_info:
        store.assert_tool_call_allowed((session.session_id,))
    assert exc_info.value.session_id == session.session_id
    assert SESSION_TERMINATION_PROMPT in str(exc_info.value)


def test_tool_input_session_ids_only_reads_semantic_argument_envelopes():
    assert store_module.tool_input_session_ids(
        {
            "session_id": "TOP00001",
            "src_session_id": "SRC00001",
            "dst_session_id": "DST00001",
            "env": {"session_id": "IGNORED1"},
            "payload": [{"session_id": "IGNORED2"}],
            "kwargs": {
                "source_session_id": "SOURCE01",
                "env": {"session_id": "IGNORED3"},
            },
            "keyword_args": {
                "destination_session_id": "DEST0001",
            },
        }
    ) == ("TOP00001", "SRC00001", "DST00001", "SOURCE01", "DEST0001")


def test_explicit_session_expiry_is_enforced_and_removes_state(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_SESSION_RETENTION_S", "0")
    clear_settings_cache()
    store = store_module.ToolSessionStore()
    store.clear()
    session = store.create_session(workdir=tmp_path, expires_at=time.time() - 1)

    with pytest.raises(ExpiredAgentSessionError, match="expired session_id"):
        store.require_session(session.session_id)

    session_dir = tmp_path / ".state" / "sessions" / session.session_id
    assert not session_dir.exists()


def test_idle_retention_prunes_sessions_when_listing(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_SESSION_RETENTION_S", "1")
    clear_settings_cache()
    clock = [100.0]
    monkeypatch.setattr(store_module.time, "time", lambda: clock[0])
    store = store_module.ToolSessionStore()
    store.clear()
    session = store.create_session(workdir=tmp_path)
    clock[0] = 102.0

    assert store.list_sessions() == []
    session_dir = tmp_path / ".state" / "sessions" / session.session_id
    assert not session_dir.exists()


def test_active_session_capacity_is_rejected_without_eviction(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_SESSION_RETENTION_S", "0")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AGENT_SESSIONS", "1")
    clear_settings_cache()
    store = store_module.ToolSessionStore()
    store.clear()
    store.create_session(workdir=tmp_path)

    with pytest.raises(RuntimeError, match="agent session limit reached"):
        store.create_session(workdir=tmp_path)


def test_inactive_session_is_evicted_to_make_capacity(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_SESSION_RETENTION_S", "0")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AGENT_SESSIONS", "1")
    clear_settings_cache()
    clock = [100.0]
    monkeypatch.setattr(store_module.time, "time", lambda: clock[0])
    store = store_module.ToolSessionStore()
    store.clear()
    first = store.create_session(workdir=tmp_path)
    clock[0] += store_module.SESSION_ACTIVE_WINDOW_S + 1

    second = store.create_session(workdir=tmp_path)

    with pytest.raises(UnknownAgentSessionError):
        store.require_session(first.session_id)
    assert store.require_session(second.session_id) == second


def test_snapshot_count_retention_keeps_newest_records(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_SESSION_RETENTION_S", "0")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_SESSION_SNAPSHOTS", "2")
    clear_settings_cache()
    clock = [100.0]
    monkeypatch.setattr(store_module.time, "time", lambda: clock[0])
    store = store_module.ToolSessionStore()
    store.clear()
    session = store.create_session(workdir=tmp_path)
    records = []
    for index in range(3):
        clock[0] += 1
        records.append(
            store.record_file_snapshot(
                session_id=session.session_id,
                path=f"{index}.txt",
                file_sha256=str(index),
                total_lines=1,
                seen_ranges=((1, 1),),
            )
        )

    assert (
        store.get_snapshot(session.session_id, records[0].snapshot_id) is None
    )
    assert (
        store.get_snapshot(session.session_id, records[1].snapshot_id)
        is not None
    )
    assert (
        store.get_snapshot(session.session_id, records[2].snapshot_id)
        is not None
    )


def test_snapshot_metadata_rejects_one_record_over_byte_limit(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_SESSION_RETENTION_S", "0")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_SESSION_SNAPSHOT_BYTES", "1024")
    clear_settings_cache()
    store = store_module.ToolSessionStore()
    store.clear()
    session = store.create_session(workdir=tmp_path)

    with pytest.raises(ValueError, match="max_session_snapshot_bytes"):
        store.record_file_snapshot(
            session_id=session.session_id,
            path="large.txt",
            file_sha256="a" * 64,
            total_lines=2_000,
            seen_ranges=tuple((line, line) for line in range(1, 2_001)),
        )


def test_expired_session_with_active_job_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_SESSION_RETENTION_S", "0")
    clear_settings_cache()
    store = store_module.ToolSessionStore()
    store.clear()
    session = store.create_session(workdir=tmp_path, expires_at=time.time() - 1)
    store._state_store.write_json(
        store._state_store.layout.jobs_store_path,
        {
            "version": 1,
            "jobs": [
                {
                    "job_id": "job_active",
                    "session_id": session.session_id,
                    "status": "running",
                }
            ],
        },
    )

    assert store.require_session(session.session_id) == session


def test_stale_managed_job_from_prior_runtime_does_not_block_expiry(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_SESSION_RETENTION_S", "0")
    clear_settings_cache()
    store = store_module.ToolSessionStore()
    store.clear()
    session = store.create_session(workdir=tmp_path, expires_at=time.time() - 1)
    store._state_store.write_json(
        store._state_store.layout.jobs_store_path,
        {
            "version": 1,
            "jobs": [
                {
                    "job_id": "job_stale_managed",
                    "session_id": session.session_id,
                    "kind": "managed",
                    "status": "running",
                    "runtime_instance_id": "previous-process",
                }
            ],
        },
    )

    with pytest.raises(ExpiredAgentSessionError):
        store.require_session(session.session_id)


def test_current_runtime_managed_job_still_protects_expired_session(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_SESSION_RETENTION_S", "0")
    clear_settings_cache()
    store = store_module.ToolSessionStore()
    store.clear()
    session = store.create_session(workdir=tmp_path, expires_at=time.time() - 1)
    store._state_store.write_json(
        store._state_store.layout.jobs_store_path,
        {
            "version": 1,
            "jobs": [
                {
                    "job_id": "job_current_managed",
                    "session_id": session.session_id,
                    "kind": "managed",
                    "status": "running",
                    "runtime_instance_id": store_module.PROCESS_INSTANCE_ID,
                }
            ],
        },
    )

    assert store.require_session(session.session_id) == session


@pytest.mark.parametrize(
    ("status", "path_key"),
    [("running", "status_path"), ("retrying", "pending_status_path")],
)
def test_durable_job_completion_no_longer_blocks_session_expiry(
    tmp_path, monkeypatch, status, path_key
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_SESSION_RETENTION_S", "0")
    clear_settings_cache()
    store = store_module.ToolSessionStore()
    store.clear()
    session = store.create_session(workdir=tmp_path, expires_at=time.time() - 1)
    status_path = tmp_path / ".state" / "jobs" / f"job_{status}.status.json"
    store._state_store.write_json(
        status_path,
        {"exit_code": 0, "completed_at": time.time()},
    )
    store._state_store.write_json(
        store._state_store.layout.jobs_store_path,
        {
            "version": 1,
            "jobs": [
                {
                    "job_id": f"job_{status}",
                    "session_id": session.session_id,
                    "status": status,
                    path_key: str(status_path),
                }
            ],
        },
    )

    with pytest.raises(ExpiredAgentSessionError):
        store.require_session(session.session_id)


def test_expired_remote_session_binding_is_preserved_for_explicit_cleanup(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_SESSION_RETENTION_S", "0")
    clear_settings_cache()
    store = store_module.ToolSessionStore()
    store.clear()
    session = store.create_session(
        target="remote",
        workdir="/remote/work",
        machine="worker-a",
        worker_session_id="WORKER12",
        expires_at=time.time() - 1,
    )

    with pytest.raises(ExpiredAgentSessionError, match="call session_end"):
        store.require_session(session.session_id)

    session_dir = tmp_path / ".state" / "sessions" / session.session_id
    assert session_dir.exists()
    assert store.list_sessions() == [session]

    prepared = store.prepare_session_termination(session.session_id)
    assert prepared.worker_session_id == "WORKER12"
    assert prepared.expires_at is None
    assert prepared.termination_requested_at is not None
    assert store.end_session(session.session_id) == prepared
    assert not session_dir.exists()


def test_inactive_remote_session_is_not_evicted_without_worker_cleanup(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_SESSION_RETENTION_S", "0")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AGENT_SESSIONS", "1")
    clear_settings_cache()
    clock = [100.0]
    monkeypatch.setattr(store_module.time, "time", lambda: clock[0])
    store = store_module.ToolSessionStore()
    store.clear()
    remote = store.create_session(
        target="remote",
        workdir="/remote/work",
        machine="worker-a",
        worker_session_id="WORKER12",
    )
    clock[0] += store_module.SESSION_ACTIVE_WINDOW_S + 1

    with pytest.raises(RuntimeError, match="agent session limit reached"):
        store.create_session(workdir=tmp_path)

    assert store.list_sessions() == [remote]


def test_pruning_loads_active_job_owners_once(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_SESSION_RETENTION_S", "0")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AGENT_SESSIONS", "3")
    clear_settings_cache()
    clock = [100.0]
    monkeypatch.setattr(store_module.time, "time", lambda: clock[0])
    store = store_module.ToolSessionStore()
    store.clear()
    for _ in range(3):
        store.create_session(workdir=tmp_path)
        clock[0] += 1

    clock[0] += store_module.SESSION_ACTIVE_WINDOW_S + 1
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AGENT_SESSIONS", "1")
    clear_settings_cache()
    original_read_json = store._state_store.read_json
    job_store_reads = 0

    def counted_read_json(path, *, max_bytes=None):
        nonlocal job_store_reads
        if path == store._state_store.layout.jobs_store_path:
            job_store_reads += 1
        return original_read_json(path, max_bytes=max_bytes)

    monkeypatch.setattr(store._state_store, "read_json", counted_read_json)

    assert len(store.list_sessions()) == 1
    assert job_store_reads == 1
