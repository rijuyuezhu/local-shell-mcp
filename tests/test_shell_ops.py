import asyncio
import time

import pytest
from fastapi.testclient import TestClient

import local_shell_mcp.http_app as http_app_module
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.http_app import build_http_app
from local_shell_mcp.mcp_app import build_mcp
from local_shell_mcp.models import CommandResult
from local_shell_mcp.ops.shell_ops import (
    public_run_shell_timeout,
    run_shell,
    send_shell,
)
from local_shell_mcp.tools.registry import common as common_tools_module
from local_shell_mcp.tools.registry import filesystem as fs_tools_module
from local_shell_mcp.tools.registry import shell as shell_tools_module
from tests.helpers import mcp_text


@pytest.mark.asyncio
async def test_run_shell_tool_rejects_timeout_above_public_cap(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    response = await build_mcp().call_tool(
        "run_shell_tool", {"command": "echo ok", "timeout_s": 3600}
    )
    payload = mcp_text(response)

    assert "timeout_s must be <= 60 seconds for public run_shell" in payload


@pytest.mark.asyncio
async def test_mcp_tool_watchdog_returns_handled_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(common_tools_module, "PUBLIC_TOOL_TIMEOUT_S", 0.01)
    clear_settings_cache()

    async def hanging_public_run_shell(
        command: str,
        cwd: str = ".",
        timeout_s: int | None = None,
        max_output_bytes: int | None = None,
    ):
        await asyncio.sleep(5)

    monkeypatch.setattr(
        shell_tools_module, "public_run_shell", hanging_public_run_shell
    )

    response = await build_mcp().call_tool(
        "run_shell_tool", {"command": "echo ok"}
    )
    payload = mcp_text(response)

    assert "run_shell_tool exceeded 0.01 second public tool timeout" in payload


def test_rest_tool_watchdog_returns_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setattr(http_app_module, "PUBLIC_TOOL_TIMEOUT_S", 0.01)
    clear_settings_cache()

    async def hanging_run_shell_handler(args: dict):
        await asyncio.sleep(5)

    monkeypatch.setitem(
        shell_tools_module.SHELL_HTTP_HANDLERS,
        "run_shell_tool",
        hanging_run_shell_handler,
    )

    response = TestClient(build_http_app()).post(
        "/tools/run_shell", json={"command": "echo ok"}
    )

    assert response.status_code == 504
    assert response.json()["error"] == "tool_timeout"


def test_rest_tool_watchdog_times_out_sync_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setattr(http_app_module, "PUBLIC_TOOL_TIMEOUT_S", 0.01)
    clear_settings_cache()

    def blocking_list_dir(*args, **kwargs):
        time.sleep(0.2)
        return []

    monkeypatch.setattr(fs_tools_module, "list_dir", blocking_list_dir)

    response = TestClient(build_http_app()).post(
        "/tools/list_files", json={"path": "."}
    )

    assert response.status_code == 504
    assert response.json()["error"] == "tool_timeout"


@pytest.mark.asyncio
async def test_mcp_tool_watchdog_times_out_sync_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(common_tools_module, "PUBLIC_TOOL_TIMEOUT_S", 0.01)
    clear_settings_cache()

    def blocking_list_dir(*args, **kwargs):
        time.sleep(0.2)
        return []

    monkeypatch.setattr(fs_tools_module, "list_dir", blocking_list_dir)

    response = await build_mcp().call_tool("list_files", {"path": "."})
    payload = mcp_text(response)

    assert "list_files exceeded 0.01 second public tool timeout" in payload


def test_public_run_shell_timeout_uses_ten_second_default(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_DEFAULT_TIMEOUT_S", "3600")
    clear_settings_cache()

    assert public_run_shell_timeout(None) == 10


def test_public_run_shell_timeout_allows_explicit_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    assert public_run_shell_timeout(60) == 60


@pytest.mark.asyncio
async def test_run_shell_timeout_includes_subprocess_spawn(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    async def hanging_spawn(command: str, cwd: str):
        await asyncio.sleep(5)

    monkeypatch.setattr(
        "local_shell_mcp.ops.shell_ops._spawn_process", hanging_spawn
    )

    result = await run_shell("echo never", timeout_s=1)

    assert result.ok is False
    assert result.timed_out is True
    assert result.exit_code is None
    assert "Timed out while starting subprocess" in result.stderr


@pytest.mark.asyncio
async def test_run_shell_fast_command_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    result = await run_shell("echo ok", timeout_s=5)

    assert result.ok is True
    assert result.timed_out is False
    assert "ok" in result.stdout


@pytest.mark.asyncio
async def test_run_shell_streams_and_bounds_large_output(tmp_path, monkeypatch):
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
async def test_run_shell_timeout_marks_result_and_cleans_up(
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

    monkeypatch.setattr("local_shell_mcp.ops.shell_ops.tmux", fake_tmux)

    result = await asyncio.wait_for(
        send_shell("session-1", "echo ok", enter=True), timeout=1
    )

    assert result == {"session_id": "session-1", "sent_bytes": 7, "enter": True}
    assert calls == [(["send-keys", "-t", "session-1", "echo ok", "Enter"], 10)]


@pytest.mark.asyncio
async def test_run_shell_filters_server_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN", "should-not-leak")
    monkeypatch.setenv("PYTHONPATH", "/app/src")
    clear_settings_cache()

    result = await run_shell(
        "env | grep -E '^(PYTHONPATH|LOCAL_SHELL_MCP_)=' || true",
        cwd=str(tmp_path),
    )

    assert result.ok
    assert result.stdout == ""
