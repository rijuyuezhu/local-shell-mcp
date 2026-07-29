from types import SimpleNamespace

import pytest

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.ops import session as session_ops
from local_shell_mcp.tool_session.store import get_tool_session_store


def test_git_output_detaches_child_stdin(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="main\n")

    monkeypatch.setattr(session_ops.subprocess, "run", fake_run)

    assert (
        session_ops._git_output(["branch", "--show-current"], tmp_path)
        == "main"
    )
    assert calls[0][0] == ["git", "branch", "--show-current"]
    assert calls[0][1]["stdin"] is session_ops.subprocess.DEVNULL
    assert calls[0][1]["timeout"] == 5


@pytest.mark.asyncio
async def test_local_session_start_offloads_orientation(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    get_tool_session_store().clear()
    calls = []

    async def fake_to_thread(function, *args, **kwargs):
        calls.append((function, args, kwargs))
        return function(*args, **kwargs)

    monkeypatch.setattr(session_ops.asyncio, "to_thread", fake_to_thread)

    result = await session_ops.session_start_execute(".", label="test")

    assert calls == [
        (
            session_ops._start_local_session,
            (),
            {"workdir": ".", "machine": None, "label": "test"},
        )
    ]
    assert result.workdir == str(tmp_path)
    assert result.label == "test"


@pytest.mark.asyncio
async def test_session_change_cwd_refreshes_environment_git_and_instructions(
    tmp_path, monkeypatch
):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (second / "AGENTS.md").write_text("instructions\n", encoding="utf-8")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    get_tool_session_store().clear()

    started = await session_ops.session_start_execute(str(first))
    changed = await session_ops.session_change_cwd_execute(
        started.session_id, str(second)
    )

    assert changed.session_id == started.session_id
    assert changed.workdir == str(second)
    assert changed.environment.workspace.workdir == str(second)
    assert changed.environment.workspace.workspace_root == str(tmp_path)
    assert changed.instruction_files == ["second/AGENTS.md"]
    assert changed.environment.runtime.python_version
    assert changed.environment.policy.max_output_bytes > 0
    assert set(changed.environment.tools.model_dump()) == {
        "shell",
        "git",
        "ripgrep",
        "tmux",
        "curl",
        "bun",
        "chromium",
        "playwright",
        "opentui",
    }


@pytest.mark.asyncio
async def test_session_end_stops_jobs_before_removing_local_state(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(workdir=tmp_path)
    calls: list[str] = []

    async def fake_stop_owned_jobs(session_id: str) -> list[str]:
        calls.append(session_id)
        assert store.require_session(session_id) == session
        return ["job_one"]

    monkeypatch.setattr(session_ops, "_stop_owned_jobs", fake_stop_owned_jobs)

    result = await session_ops.session_end_execute(session.session_id)

    assert calls == [session.session_id]
    assert result.ended is True
    assert result.stopped_jobs == ["job_one"]
    with pytest.raises(ValueError, match="unknown session_id"):
        store.require_session(session.session_id)


@pytest.mark.asyncio
async def test_remote_session_end_removes_worker_before_controller_state(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(
        target="remote",
        workdir="/remote/work",
        machine="worker-a",
        worker_session_id="WORKER12",
    )
    calls: list[tuple[str, str]] = []

    async def fake_stop_owned_jobs(session_id: str) -> list[str]:
        return []

    async def fake_remote_call(remote_session, tool, args):
        calls.append((remote_session.session_id, tool))
        assert args == {}
        assert store.require_session(remote_session.session_id) == session
        return {"ended": True}

    monkeypatch.setattr(session_ops, "_stop_owned_jobs", fake_stop_owned_jobs)
    monkeypatch.setattr(
        "local_shell_mcp.ops.utils.remote_session.call_remote_session_tool",
        fake_remote_call,
    )

    result = await session_ops.session_end_execute(session.session_id)

    assert calls == [(session.session_id, "session_end")]
    assert result.target == "remote"
    assert result.machine == "worker-a"
    with pytest.raises(ValueError, match="unknown session_id"):
        store.require_session(session.session_id)
