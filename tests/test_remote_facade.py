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
@pytest.mark.parametrize(
    ("args", "expected_tool", "expected_args"),
    [
        (
            {
                "action": "send",
                "shell_id": "sh1",
                "input_text": "go",
                "enter": False,
            },
            "send_persistent_shell_input",
            {"shell_id": "sh1", "input_text": "go", "enter": False},
        ),
        (
            {"action": "read", "shell_id": "sh1", "lines": 20},
            "read_persistent_shell_output",
            {"shell_id": "sh1", "lines": 20},
        ),
        (
            {"action": "kill", "shell_id": "sh1"},
            "kill_persistent_shell",
            {"shell_id": "sh1"},
        ),
        ({"action": "list"}, "list_persistent_shells", {}),
    ],
)
async def test_remote_maps_session_actions(
    monkeypatch, args, expected_tool, expected_args
):
    calls = []

    async def fake_call(machine, tool, worker_args, timeout_s=None):
        calls.append((machine, tool, worker_args, timeout_s))
        return {"ok": True, "data": {"tool": tool, "ok": True}}

    monkeypatch.setattr(remote_ops, "call_remote_worker_tool", fake_call)

    result = await remote_ops.remote_execute("worker-a", "session", args)

    assert result.op == "session"
    assert result.tool == expected_tool
    assert result.data["tool"] == expected_tool
    assert calls == [("worker-a", expected_tool, expected_args, None)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "args", "impl_name", "expected_call"),
    [
        (
            "pull_file",
            {
                "remote_path": "remote/in.bin",
                "local_path": "local/in.bin",
                "overwrite": False,
                "chunk_size": 8,
            },
            "remote_pull_file_execute",
            ("worker-a", "remote/in.bin", "local/in.bin", False, 8),
        ),
        (
            "push_file",
            {
                "local_path": "local/out.bin",
                "remote_path": "remote/out.bin",
                "overwrite": False,
                "chunk_size": 8,
            },
            "remote_push_file_execute",
            ("local/out.bin", "worker-a", "remote/out.bin", False, 8),
        ),
        (
            "pull_dir",
            {
                "remote_path": "remote/dir",
                "local_path": "local/dir",
                "overwrite": True,
                "chunk_size": 8,
            },
            "remote_pull_dir_execute",
            ("worker-a", "remote/dir", "local/dir", True, 8),
        ),
        (
            "push_dir",
            {
                "local_path": "local/dir",
                "remote_path": "remote/dir",
                "overwrite": True,
                "chunk_size": 8,
            },
            "remote_push_dir_execute",
            ("local/dir", "worker-a", "remote/dir", True, 8),
        ),
        (
            "copy_file",
            {
                "src_machine": "worker-src",
                "src_path": "src.bin",
                "dst_machine": "worker-dst",
                "dst_path": "dst.bin",
                "overwrite": False,
                "chunk_size": 8,
            },
            "remote_copy_file_execute",
            ("worker-src", "src.bin", "worker-dst", "dst.bin", False, 8),
        ),
        (
            "copy_dir",
            {
                "src_path": "src-dir",
                "dst_machine": "worker-dst",
                "dst_path": "dst-dir",
                "overwrite": True,
                "chunk_size": 8,
            },
            "remote_copy_dir_execute",
            ("worker-a", "src-dir", "worker-dst", "dst-dir", True, 8),
        ),
    ],
)
async def test_remote_maps_transfer_actions(
    monkeypatch, action, args, impl_name, expected_call
):
    calls = []

    async def fake_transfer(*call_args):
        calls.append(call_args)
        return {"action": action, "bytes": 4, "chunks": 2}

    monkeypatch.setattr(remote_ops, impl_name, fake_transfer)

    result = await remote_ops.remote_execute(
        "worker-a", "transfer", {"action": action, **args}
    )

    assert result.op == "transfer"
    assert result.tool == f"remote_transfer:{action}"
    assert result.data == {"action": action, "bytes": 4, "chunks": 2}
    assert calls == [expected_call]


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
