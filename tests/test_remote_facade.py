import pytest

import local_shell_mcp.ops.files as file_ops
import local_shell_mcp.ops.jobs as job_ops
import local_shell_mcp.ops.read as read_ops
import local_shell_mcp.ops.remote as remote_ops
import local_shell_mcp.ops.search as search_ops
import local_shell_mcp.ops.session as session_ops
import local_shell_mcp.ops.shell as shell_ops
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.server.mcp.app import build_mcp
from local_shell_mcp.tool_session.store import get_tool_session_store
from tests.helpers import mcp_structured


@pytest.mark.asyncio
async def test_remote_admin_lists(monkeypatch):
    monkeypatch.setattr(
        remote_ops,
        "list_remote_machines",
        lambda: {"machines": [], "counts": {"total": 0}},
    )

    result = await remote_ops.remote_admin_execute("list", {})

    assert result.action == "list"
    assert result.data == {"machines": [], "counts": {"total": 0}}


@pytest.mark.asyncio
async def test_remote_admin_is_exposed_in_mcp(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODE", "mcp")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()
    monkeypatch.setattr(
        remote_ops,
        "list_remote_machines",
        lambda: {"machines": [], "counts": {"total": 0}},
    )

    result = mcp_structured(
        await build_mcp().call_tool(
            "remote_admin", {"action": "list", "args": {}}
        )
    )

    assert result == {
        "action": "list",
        "data": {"machines": [], "counts": {"total": 0}},
    }


def _remote_read_payload(worker_session_id="WORKER12"):
    return {
        "kind": "file",
        "path": "demo.txt",
        "raw": False,
        "content": "1|hello",
        "file": {
            "path": "demo.txt",
            "bytes": 6,
            "bytes_read": 6,
            "truncated_bytes": 0,
            "total_lines": 1,
            "start_line": 1,
            "end_line": 1,
            "line_count": 1,
            "lines": [{"line": 1, "text": "hello"}],
            "numbered_content": "1|hello",
            "session_id": worker_session_id,
            "snapshot_id": "snap1",
            "file_sha256": "abc",
            "seen_ranges": [{"start": 1, "end": 1}],
            "truncated": False,
            "content": "hello",
        },
    }


def _remote_search_payload(worker_session_id="WORKER12"):
    return {
        "ok": True,
        "matches": [
            {
                "path": "demo.txt",
                "line": 1,
                "column": 1,
                "text": "hello",
                "numbered_line": "1|hello",
                "session_id": worker_session_id,
                "snapshot_id": "snap-search",
                "file_sha256": "abc",
                "seen_range": {"start": 1, "end": 1},
            }
        ],
        "count": 1,
        "truncated": False,
        "stderr": "",
        "numbered_content": "demo.txt\n1|hello",
    }


def _remote_edit_payload(worker_session_id="WORKER12"):
    payload = _remote_read_payload(worker_session_id)["file"]
    payload.update(
        {
            "numbered_content": "1|changed",
            "content": "changed",
            "lines": [{"line": 1, "text": "changed"}],
            "snapshot_id": "snap-edit",
        }
    )
    return {
        "path": "demo.txt",
        "start_line": 1,
        "end_line": 1,
        "replacement_line_count": 1,
        "diff": "--- demo.txt\n+++ demo.txt\n",
        "context": payload,
    }


def _remote_job_payload(worker_session_id="WORKER12"):
    return {
        "operation": "list",
        "jobs": [
            {
                "job_id": "job_1",
                "name": "job_1",
                "status": "running",
                "command": "sleep 1",
                "cwd": "/remote/project",
                "session_id": worker_session_id,
                "created_at": 1.0,
                "updated_at": 1.0,
                "last_started_at": 1.0,
                "attempts": 1,
            }
        ],
        "counts": {"running": 1},
        "outputs": [],
        "cancelled": [],
        "retried": [],
        "message": None,
    }


@pytest.mark.asyncio
async def test_session_start_creates_remote_control_session(monkeypatch):
    store = get_tool_session_store()
    store.clear()
    calls = []

    async def fake_start_worker_session(*, machine, workdir, label=None):
        calls.append((machine, workdir, label))
        return {
            "session_id": "WORKER12",
            "target": "local",
            "workdir": "/remote/project",
        }

    monkeypatch.setattr(
        session_ops, "start_worker_session", fake_start_worker_session
    )

    result = await session_ops.session_start_execute(
        "project", target="remote", machine="worker-a", label="demo"
    )
    record = store.require_session(result.session_id)

    assert result.target == "remote"
    assert result.machine == "worker-a"
    assert result.workdir == "/remote/project"
    assert "worker_session_id" not in result.model_dump()
    assert record.worker_session_id == "WORKER12"
    assert calls == [("worker-a", "project", "demo")]


@pytest.mark.asyncio
async def test_session_start_remote_requires_machine():
    with pytest.raises(ValueError, match="machine is required"):
        await session_ops.session_start_execute(".", target="remote")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "match"),
    [
        (
            ValueError("unknown remote machine: worker-a"),
            "unknown remote machine",
        ),
        (RuntimeError("remote machine is offline: worker-a"), "offline"),
    ],
)
async def test_session_start_remote_surfaces_missing_or_offline_worker(
    monkeypatch, exc, match
):
    async def fake_start_worker_session(*, machine, workdir, label=None):
        raise exc

    monkeypatch.setattr(
        session_ops, "start_worker_session", fake_start_worker_session
    )

    with pytest.raises(type(exc), match=match):
        await session_ops.session_start_execute(
            "/remote/project", target="remote", machine="worker-a"
        )


@pytest.mark.asyncio
async def test_remote_session_dispatches_read_search_edit_bash_job(monkeypatch):
    store = get_tool_session_store()
    store.clear()
    control = store.create_session(
        target="remote",
        workdir="/remote/project",
        machine="worker-a",
        worker_session_id="WORKER12",
    )
    calls = []

    async def fake_call(machine, tool, args, timeout_s=None):
        calls.append((machine, tool, args, timeout_s))
        data_by_tool = {
            "read": _remote_read_payload(),
            "search": _remote_search_payload(),
            "edit_lines": _remote_edit_payload(),
            "bash": {
                "mode": "command",
                "command": "printf hi",
                "cwd": "/remote/project",
                "result": {"ok": True, "stdout": "hi", "stderr": ""},
            },
            "job": _remote_job_payload(),
        }
        return {"ok": True, "data": data_by_tool[tool]}

    monkeypatch.setattr(
        "local_shell_mcp.ops.utils.remote_session.call_remote_worker_tool",
        fake_call,
    )

    read_result = await read_ops.read_execute("demo.txt:1", control.session_id)
    search_result = await search_ops.search_execute(
        "hello", session_id=control.session_id, regex=False
    )
    edit_result = await file_ops.edit_lines_dispatch_execute(
        "demo.txt", 1, 1, "changed", "snap1", control.session_id
    )
    bash_result = await shell_ops.bash_execute(
        control.session_id, "printf hi", timeout_s=5
    )
    job_result = await job_ops.job_execute(control.session_id)

    assert read_result.file is not None
    assert read_result.file.session_id == control.session_id
    assert search_result.matches[0].session_id == control.session_id
    assert edit_result.context.session_id == control.session_id
    assert bash_result.result["stdout"] == "hi"
    assert job_result.jobs[0].session_id == control.session_id
    assert calls == [
        (
            "worker-a",
            "read",
            {"path": "demo.txt:1", "session_id": "WORKER12"},
            None,
        ),
        (
            "worker-a",
            "search",
            {
                "pattern": "hello",
                "paths": None,
                "regex": False,
                "case_sensitive": True,
                "max_results": None,
                "session_id": "WORKER12",
            },
            None,
        ),
        (
            "worker-a",
            "edit_lines",
            {
                "path": "demo.txt",
                "start_line": 1,
                "end_line": 1,
                "replacement": "changed",
                "snapshot_id": "snap1",
                "session_id": "WORKER12",
            },
            None,
        ),
        (
            "worker-a",
            "bash",
            {
                "command": "printf hi",
                "cwd": ".",
                "timeout_s": 5,
                "max_output_bytes": None,
                "env": None,
                "async_": False,
                "pty": False,
                "name": None,
                "session_id": "WORKER12",
            },
            5,
        ),
        (
            "worker-a",
            "job",
            {
                "list_jobs": False,
                "poll": None,
                "cancel": None,
                "retry": None,
                "include_finished": True,
                "lines": 200,
                "session_id": "WORKER12",
            },
            None,
        ),
    ]


@pytest.mark.asyncio
async def test_remote_session_rejects_pty_bash(monkeypatch):
    store = get_tool_session_store()
    store.clear()
    control = store.create_session(
        target="remote",
        workdir="/remote/project",
        machine="worker-a",
        worker_session_id="WORKER12",
    )

    with pytest.raises(ValueError, match="PTY shell mode"):
        await shell_ops.bash_execute(control.session_id, "python -i", pty=True)


@pytest.mark.asyncio
async def test_remote_session_dispatch_surfaces_worker_error(monkeypatch):
    store = get_tool_session_store()
    store.clear()
    control = store.create_session(
        target="remote",
        workdir="/remote/project",
        machine="worker-a",
        worker_session_id="WORKER12",
    )

    async def fake_call(machine, tool, args, timeout_s=None):
        return {
            "ok": True,
            "data": {
                "status": "error",
                "error_type": "FileNotFoundError",
                "message": "missing.txt",
            },
        }

    monkeypatch.setattr(
        "local_shell_mcp.ops.utils.remote_session.call_remote_worker_tool",
        fake_call,
    )

    with pytest.raises(RuntimeError, match="FileNotFoundError: missing.txt"):
        await read_ops.read_execute("missing.txt", control.session_id)
