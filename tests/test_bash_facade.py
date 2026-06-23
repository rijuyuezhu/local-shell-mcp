import pytest

import local_shell_mcp.ops.bash as bash_ops
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.schemas.result_models.jobs import JobStartOutput
from local_shell_mcp.schemas.result_models.shell import (
    StartPersistentShellOutput,
)
from local_shell_mcp.server.mcp.app import build_mcp
from tests.helpers import mcp_structured


@pytest.mark.asyncio
async def test_bash_facade_runs_bounded_command(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    result = await bash_ops.bash_execute(
        "sh -c 'printf \"$FOO\"'", cwd=".", env={"FOO": "hello"}
    )

    assert result.mode == "command"
    assert result.command == "sh -c 'printf \"$FOO\"'"
    assert result.result["ok"] is True
    assert result.result["stdout"] == "hello"


@pytest.mark.asyncio
async def test_bash_facade_routes_async_to_job(monkeypatch):
    calls = []

    async def fake_job_start(command, cwd=".", name=None):
        calls.append((command, cwd, name))
        return JobStartOutput.model_validate(
            {
                "job_id": "job_123",
                "name": name,
                "status": "running",
                "command": command,
                "cwd": cwd,
                "session_id": "session-1",
                "backend": "tmux",
                "created_at": 1.0,
                "updated_at": 1.0,
                "last_started_at": 1.0,
                "attempts": 1,
            }
        )

    monkeypatch.setattr(bash_ops, "job_start_execute", fake_job_start)

    result = await bash_ops.bash_execute(
        "npm test", cwd="app", async_=True, name="tests"
    )

    assert result.mode == "job"
    assert result.result["job_id"] == "job_123"
    assert calls == [("npm test", "app", "tests")]


@pytest.mark.asyncio
async def test_bash_facade_routes_pty_to_persistent_shell(monkeypatch):
    calls = []

    async def fake_start_shell(cwd=".", name=None, command=None):
        calls.append((cwd, name, command))
        return StartPersistentShellOutput.model_validate(
            {
                "session_id": "session-1",
                "name": "server",
                "cwd": cwd,
                "backend": "tmux",
                "started": True,
            }
        )

    monkeypatch.setattr(
        bash_ops, "start_persistent_shell_execute", fake_start_shell
    )

    result = await bash_ops.bash_execute(
        "python -i", cwd=".", pty=True, name="server"
    )

    assert result.mode == "pty"
    assert result.result["session_id"] == "session-1"
    assert calls == [(".", "server", "python -i")]


@pytest.mark.asyncio
async def test_bash_facade_is_exposed_in_mcp(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    payload = mcp_structured(
        await build_mcp().call_tool("bash", {"command": "printf hi"})
    )

    assert payload["mode"] == "command"
    assert payload["result"]["stdout"] == "hi"
