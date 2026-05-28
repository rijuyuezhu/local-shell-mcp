import asyncio

import pytest

from local_shell_mcp.models import CommandResult
from local_shell_mcp.settings import get_settings
from local_shell_mcp.shell_ops import public_run_shell_timeout, run_shell, send_shell
from local_shell_mcp.tools import build_mcp


@pytest.mark.asyncio
async def test_run_shell_tool_rejects_timeout_above_public_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    response = await build_mcp().call_tool("run_shell_tool", {"command": "echo ok", "timeout_s": 3600})
    payload = response[0].text

    assert "timeout_s must be <= 60 seconds for public run_shell" in payload


def test_public_run_shell_timeout_caps_omitted_default(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_DEFAULT_TIMEOUT_S", "3600")
    get_settings.cache_clear()

    assert public_run_shell_timeout(None) == 60


@pytest.mark.asyncio
async def test_run_shell_timeout_includes_subprocess_spawn(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    async def hanging_spawn(command: str, cwd: str):  # noqa: ARG001
        await asyncio.sleep(5)

    monkeypatch.setattr("local_shell_mcp.shell_ops._spawn_process", hanging_spawn)

    result = await run_shell("echo never", timeout_s=1)

    assert result.ok is False
    assert result.timed_out is True
    assert result.exit_code is None
    assert "Timed out while starting subprocess" in result.stderr


@pytest.mark.asyncio
async def test_run_shell_fast_command_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    result = await run_shell("echo ok", timeout_s=5)

    assert result.ok is True
    assert result.timed_out is False
    assert "ok" in result.stdout


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

    monkeypatch.setattr("local_shell_mcp.shell_ops.tmux", fake_tmux)

    result = await asyncio.wait_for(send_shell("session-1", "echo ok", enter=True), timeout=1)

    assert result == {"session_id": "session-1", "sent_bytes": 7, "enter": True}
    assert calls == [(["send-keys", "-t", "session-1", "echo ok", "Enter"], 10)]
