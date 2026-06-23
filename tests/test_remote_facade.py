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

    assert result.tool == "run_shell_command"
    assert result.data["stdout"] == "done"
    assert calls == [
        (
            "worker-a",
            "run_shell_command",
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
