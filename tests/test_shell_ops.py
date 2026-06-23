import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError

import local_shell_mcp.server.http.tool_routes as http_tool_routes_module
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.ops.shell import (
    clamp_timeout,
    run_shell,
    run_shell_command_timeout,
    send_persistent_shell_input_execute,
)
from local_shell_mcp.schemas.result_models.shell import CommandResult
from local_shell_mcp.server.http.app import build_http_app
from local_shell_mcp.server.mcp.app import build_mcp
from local_shell_mcp.tool_session.store import get_tool_session_store
from local_shell_mcp.tools.registry import bash as bash_tools_module
from local_shell_mcp.tools.registry import files as fs_tools_module
from tests.helpers import mcp_structured


@pytest.mark.asyncio
async def test_bash_rejects_timeout_above_public_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    mcp = build_mcp()
    session = mcp_structured(
        await mcp.call_tool("session_start", {"workdir": "."})
    )

    with pytest.raises(ToolError, match="timeout_s must be <= 60 seconds"):
        await mcp.call_tool(
            "bash",
            {
                "session_id": session["session_id"],
                "command": "echo ok",
                "timeout_s": 3600,
            },
        )


@pytest.mark.asyncio
async def test_mcp_tool_watchdog_returns_handled_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_TOOL_TIMEOUT_S", "0.01")
    clear_settings_cache()

    async def hanging_bash_execute(*args, **kwargs):
        await asyncio.sleep(5)

    monkeypatch.setattr(
        bash_tools_module,
        "bash_execute",
        hanging_bash_execute,
    )

    session_id = get_tool_session_store().create_session(workdir=".").session_id
    mcp = build_mcp()

    with pytest.raises(
        ToolError,
        match="bash exceeded 0.01 second tool timeout",
    ):
        await mcp.call_tool(
            "bash",
            {"session_id": session_id, "command": "echo ok"},
        )


def test_rest_tool_watchdog_returns_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_TOOL_TIMEOUT_S", "0.01")
    clear_settings_cache()

    async def hanging_call_local_tool(*args, **kwargs):
        await asyncio.sleep(5)

    monkeypatch.setattr(
        http_tool_routes_module, "call_local_tool", hanging_call_local_tool
    )

    response = TestClient(build_http_app()).post(
        "/tools/bash", json={"command": "echo ok"}
    )

    assert response.status_code == 504
    assert response.json()["error"] == "tool_timeout"


def test_rest_tool_watchdog_times_out_sync_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_TOOL_TIMEOUT_S", "0.01")
    clear_settings_cache()

    def blocking_list_dir(*args, **kwargs):
        time.sleep(0.2)
        return []

    monkeypatch.setattr(
        fs_tools_module, "list_files_execute", blocking_list_dir
    )

    response = TestClient(build_http_app()).post(
        "/tools/list_files", json={"path": "."}
    )

    assert response.status_code == 504
    assert response.json()["error"] == "tool_timeout"


@pytest.mark.asyncio
async def test_mcp_tool_watchdog_times_out_sync_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_TOOL_TIMEOUT_S", "0.01")
    clear_settings_cache()

    def blocking_list_dir(*args, **kwargs):
        time.sleep(0.2)
        return []

    monkeypatch.setattr(
        fs_tools_module, "list_files_execute", blocking_list_dir
    )

    with pytest.raises(
        ToolError, match="list_files exceeded 0.01 second tool timeout"
    ):
        await build_mcp().call_tool("list_files", {"path": "."})


def test_run_shell_command_timeout_uses_ten_second_default(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_RUN_SHELL_DEFAULT_TIMEOUT_S", "10")
    clear_settings_cache()

    assert run_shell_command_timeout(None) == 10


def test_run_shell_command_timeout_allows_explicit_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    assert run_shell_command_timeout(60) == 60


def test_internal_shell_timeout_uses_at_least_builtin_default(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_RUN_SHELL_DEFAULT_TIMEOUT_S", "5")
    clear_settings_cache()

    assert clamp_timeout(None) == 60


def test_internal_shell_timeout_uses_larger_run_shell_values(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_RUN_SHELL_DEFAULT_TIMEOUT_S", "120")
    monkeypatch.setenv("LOCAL_SHELL_MCP_RUN_SHELL_MAX_TIMEOUT_S", "7200")
    clear_settings_cache()

    assert clamp_timeout(None) == 120
    assert clamp_timeout(9999) == 7200


@pytest.mark.asyncio
async def test_run_shell_command_timeout_includes_subprocess_spawn(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    async def hanging_spawn(command: str, cwd: str):
        await asyncio.sleep(5)

    monkeypatch.setattr(
        "local_shell_mcp.ops.shell._spawn_process", hanging_spawn
    )

    result = await run_shell("echo never", timeout_s=1)

    assert result.ok is False
    assert result.timed_out is True
    assert result.exit_code is None
    assert "Timed out while starting subprocess" in result.stderr


@pytest.mark.asyncio
async def test_run_shell_command_fast_command_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    result = await run_shell("echo ok", timeout_s=5)

    assert result.ok is True
    assert result.timed_out is False
    assert "ok" in result.stdout


@pytest.mark.asyncio
async def test_run_shell_command_streams_and_bounds_large_output(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    result = await run_shell(
        "python3 -c 'import sys; sys.stdout.write(\"x\" * 200000)'",
        timeout_s=5,
        max_output_bytes=1000,
    )

    assert result.ok is True
    assert result.truncated is True
    assert len(result.stdout.encode()) <= 500


@pytest.mark.asyncio
async def test_run_shell_command_timeout_marks_result_and_cleans_up(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    result = await run_shell("sleep 30", timeout_s=1)

    assert result.ok is False
    assert result.timed_out is True


@pytest.mark.asyncio
async def test_send_shell_invokes_tmux_promptly(monkeypatch):
    calls = []

    async def fake_tmux(args: list[str], timeout_s: int = 10):
        calls.append((args, timeout_s))
        return CommandResult(
            ok=True,
            exit_code=0,
            timed_out=False,
            duration_ms=1,
            cwd=".",
            command="tmux",
        )

    monkeypatch.setattr("local_shell_mcp.ops.shell.tmux", fake_tmux)

    result = await asyncio.wait_for(
        send_persistent_shell_input_execute("shell-1", "echo ok", enter=True),
        timeout=1,
    )

    assert result.model_dump() == {
        "shell_id": "shell-1",
        "sent_bytes": 7,
        "enter": True,
    }
    assert calls == [(["send-keys", "-t", "shell-1", "echo ok", "Enter"], 10)]


@pytest.mark.asyncio
async def test_run_shell_command_filters_server_environment(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN", "should-not-leak")
    monkeypatch.setenv("PYTHONPATH", "/app/src")
    monkeypatch.setenv("DOCKER_RUN_AS_ROOT", "false")
    monkeypatch.setenv("DOCKER_PERSISTENT_CREDENTIALS", "true")
    monkeypatch.setenv("DOCKER_CREDENTIALS_DIR", "/persist/credentials")
    monkeypatch.setenv("DOCKER_CHOWN_WORKSPACE", "true")
    monkeypatch.setenv("CLOUDFLARE_TUNNEL_TOKEN", "should-not-leak")
    clear_settings_cache()

    result = await run_shell(
        (
            "env | grep_search_execute -E "
            "'^(PYTHONPATH|LOCAL_SHELL_MCP_|DOCKER_|CLOUDFLARE_TUNNEL_TOKEN=)' "
            "|| true"
        ),
        cwd=str(tmp_path),
    )

    assert result.ok
    assert result.stdout == ""
