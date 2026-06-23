import pytest

import local_shell_mcp.ops.remote as remote_ops
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.server.mcp.app import build_mcp
from tests.helpers import mcp_structured


@pytest.mark.asyncio
async def test_remote_facade_maps_read_to_high_level_worker_tool(monkeypatch):
    calls = []

    async def fake_call(machine, tool, args, timeout_s=None):
        calls.append((machine, tool, args, timeout_s))
        return {"ok": True, "data": {"path": "demo.py", "content": "1|x"}}

    monkeypatch.setattr(remote_ops, "call_remote_worker_tool", fake_call)

    result = await remote_ops.remote_execute(
        "worker-a", "read", {"path": "demo.py:1"}
    )

    assert result.machine == "worker-a"
    assert result.op == "read"
    assert result.tool == "read"
    assert result.data["path"] == "demo.py"
    assert calls == [("worker-a", "read", {"path": "demo.py:1"}, None)]


@pytest.mark.asyncio
async def test_remote_facade_maps_bash_timeout(monkeypatch):
    calls = []

    async def fake_call(machine, tool, args, timeout_s=None):
        calls.append((machine, tool, args, timeout_s))
        return {"ok": True, "data": {"ok": True, "stdout": "done"}}

    monkeypatch.setattr(remote_ops, "call_remote_worker_tool", fake_call)

    result = await remote_ops.remote_execute(
        "worker-a",
        "bash",
        {"command": "echo done", "timeout_s": 7},
    )

    assert result.tool == "bash"
    assert result.data["stdout"] == "done"
    assert calls == [
        (
            "worker-a",
            "bash",
            {"command": "echo done", "timeout_s": 7},
            7,
        )
    ]


@pytest.mark.asyncio
async def test_remote_facade_is_exposed_in_mcp(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODE", "mcp")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    calls = []

    async def fake_call(machine, tool, args, timeout_s=None):
        calls.append((machine, tool, args, timeout_s))
        return {"ok": True, "data": {"path": "demo.py", "content": "1|x"}}

    monkeypatch.setattr(remote_ops, "call_remote_worker_tool", fake_call)

    result = mcp_structured(
        await build_mcp().call_tool(
            "remote",
            {
                "machine": "worker-a",
                "op": "read",
                "args": {"path": "demo.py:1"},
            },
        )
    )

    assert result["machine"] == "worker-a"
    assert result["op"] == "read"
    assert result["tool"] == "read"
    assert calls == [("worker-a", "read", {"path": "demo.py:1"}, None)]


@pytest.mark.asyncio
async def test_remote_facade_maps_session_action(monkeypatch):
    calls = []

    async def fake_call(machine, tool, args, timeout_s=None):
        calls.append((machine, tool, args, timeout_s))
        return {"ok": True, "data": {"session_id": "s1", "output": "ready"}}

    monkeypatch.setattr(remote_ops, "call_remote_worker_tool", fake_call)

    result = await remote_ops.remote_execute(
        "worker-a",
        "session",
        {"action": "read", "session_id": "s1", "lines": 20},
    )

    assert result.op == "session"
    assert result.tool == "read_persistent_shell_output"
    assert result.data["session_id"] == "s1"
    assert calls == [
        (
            "worker-a",
            "read_persistent_shell_output",
            {"session_id": "s1", "lines": 20},
            None,
        )
    ]


@pytest.mark.asyncio
async def test_remote_facade_maps_transfer_action(monkeypatch):
    calls = []

    async def fake_push(
        local_path, machine, remote_path, overwrite=True, chunk_size=None
    ):
        calls.append((local_path, machine, remote_path, overwrite, chunk_size))
        return {
            "source": {"machine": "local", "path": local_path},
            "destination": {"machine": machine, "path": remote_path},
            "bytes": 4,
            "sha256": None,
            "chunks": 2,
            "chunk_size": chunk_size,
        }

    monkeypatch.setattr(remote_ops, "remote_push_file_execute", fake_push)

    result = await remote_ops.remote_execute(
        "worker-a",
        "transfer",
        {
            "action": "push_file",
            "local_path": "artifact.bin",
            "remote_path": "remote/artifact.bin",
            "chunk_size": 2,
        },
    )

    assert result.op == "transfer"
    assert result.tool == "remote_transfer:push_file"
    assert result.data["bytes"] == 4
    assert calls == [
        ("artifact.bin", "worker-a", "remote/artifact.bin", True, 2)
    ]


@pytest.mark.asyncio
async def test_remote_admin_facade_lists(monkeypatch):
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
