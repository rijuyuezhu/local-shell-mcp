import pytest

import local_shell_mcp.ops.shell as shell_ops
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.schemas.result_models.jobs import JobStartOutput
from local_shell_mcp.schemas.result_models.shell import (
    StartPersistentShellOutput,
)
from local_shell_mcp.server.mcp.app import build_mcp
from local_shell_mcp.tool_session.store import get_tool_session_store
from tests.helpers import mcp_structured


def _create_session(workdir: str = ".") -> str:
    store = get_tool_session_store()
    store.clear()
    return store.create_session(workdir=workdir).session_id


@pytest.mark.asyncio
async def test_shell_execution_runs_bounded_command_in_session_workdir(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    session_dir = tmp_path / "project"
    session_dir.mkdir()
    session_id = _create_session("project")

    result = await shell_ops.bash_execute(
        session_id,
        "sh -c 'printf \"$FOO:$PWD\"'",
        cwd=".",
        env={"FOO": "hello"},
    )

    assert result.mode == "command"
    assert result.command == "sh -c 'printf \"$FOO:$PWD\"'"
    assert result.cwd == str(session_dir)
    assert result.result["ok"] is True
    assert result.result["stdout"] == f"hello:{session_dir}"


@pytest.mark.asyncio
async def test_shell_execution_rejects_cwd_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "project").mkdir()
    (tmp_path / "other").mkdir()
    session_id = _create_session("project")

    with pytest.raises(ValueError, match="Path escapes session workdir"):
        await shell_ops.bash_execute(session_id, "pwd", cwd="../other")


@pytest.mark.asyncio
async def test_shell_execution_routes_async_to_session_job(monkeypatch):
    calls = []

    async def fake_job_start(session_id, command, cwd=".", name=None):
        calls.append((session_id, command, cwd, name))
        return JobStartOutput.model_validate(
            {
                "job_id": "job_123",
                "name": name,
                "status": "running",
                "command": command,
                "cwd": cwd,
                "session_id": session_id,
                "created_at": 1.0,
                "updated_at": 1.0,
                "last_started_at": 1.0,
                "attempts": 1,
            }
        )

    class FakeStore:
        def touch_session(self, session_id):
            from local_shell_mcp.tool_session.store import AgentSession

            return AgentSession(
                session_id=session_id,
                target="local",
                workdir="/tmp/project",
                machine=None,
                worker_session_id=None,
                created_at=1.0,
                updated_at=1.0,
            )

    monkeypatch.setattr(
        "local_shell_mcp.ops.jobs.job_start_execute", fake_job_start
    )
    monkeypatch.setattr(
        shell_ops, "get_tool_session_store", lambda: FakeStore()
    )
    monkeypatch.setattr(
        shell_ops,
        "resolve_session_path",
        lambda session, cwd, must_exist=False: "/tmp/project/app",
    )

    result = await shell_ops.bash_execute(
        "ABC12345", "npm test", cwd="app", async_=True, name="tests"
    )

    assert result.mode == "job"
    assert result.result["job_id"] == "job_123"
    assert result.result["session_id"] == "ABC12345"
    assert "backend" not in result.result
    assert calls == [("ABC12345", "npm test", "/tmp/project/app", "tests")]


@pytest.mark.asyncio
async def test_shell_execution_routes_pty_to_persistent_shell(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    session_id = _create_session()
    calls = []

    async def fake_start_shell(cwd=".", name=None, command=None):
        calls.append((cwd, name, command))
        return StartPersistentShellOutput.model_validate(
            {
                "shell_id": "shell-1",
                "name": "server",
                "cwd": cwd,
                "backend": "tmux",
                "started": True,
            }
        )

    monkeypatch.setattr(
        shell_ops, "start_persistent_shell_execute", fake_start_shell
    )

    result = await shell_ops.bash_execute(
        session_id, "python -i", cwd=".", pty=True, name="server"
    )

    assert result.mode == "pty"
    assert result.result["shell_id"] == "shell-1"
    assert calls == [(str(tmp_path), "server", "python -i")]


@pytest.mark.asyncio
async def test_shell_execution_is_exposed_in_mcp(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()
    get_tool_session_store().clear()

    mcp = build_mcp()
    session = mcp_structured(
        await mcp.call_tool("session_start", {"workdir": "."})
    )
    payload = mcp_structured(
        await mcp.call_tool(
            "bash",
            {"session_id": session["session_id"], "command": "printf hi"},
        )
    )

    assert payload["mode"] == "command"
    assert payload["cwd"] == str(tmp_path)
    assert payload["result"]["stdout"] == "hi"
