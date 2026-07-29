import asyncio
from types import SimpleNamespace

import pytest

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.jobs import runtime as jobs_runtime
from local_shell_mcp.ops import session as session_ops
from local_shell_mcp.ops.utils import remote_session as remote_session_ops
from local_shell_mcp.remote_worker import dispatch as worker_dispatch
from local_shell_mcp.tool_session.store import get_tool_session_store
from local_shell_mcp.tools.registry import session as session_registry


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
async def test_session_start_rejects_unknown_target():
    with pytest.raises(ValueError, match="target must be"):
        await session_ops.session_start_execute(".", target="elsewhere")


@pytest.mark.asyncio
async def test_remote_session_start_releases_worker_when_admission_fails(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    orientation = session_ops._session_output(
        store.create_session(workdir=tmp_path)
    ).model_copy(update={"session_id": "WORKER12", "workdir": "/remote/work"})
    store.clear()
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AGENT_SESSIONS", "1")
    clear_settings_cache()
    store.create_session(workdir=tmp_path)
    released: list[tuple[str, str]] = []

    async def fake_start_worker_session(**_kwargs):
        return orientation.model_dump()

    async def fake_end_worker_session(*, machine, worker_session_id):
        released.append((machine, worker_session_id))

    monkeypatch.setattr(
        session_ops, "start_worker_session", fake_start_worker_session
    )
    monkeypatch.setattr(
        session_ops, "end_worker_session", fake_end_worker_session
    )

    with pytest.raises(RuntimeError, match="agent session limit reached"):
        await session_ops.session_start_execute(
            "/remote/work", target="remote", machine="worker-a"
        )

    assert released == [("worker-a", "WORKER12")]


@pytest.mark.asyncio
async def test_end_worker_session_dispatches_worker_session_id(monkeypatch):
    calls = []

    async def fake_call(machine, tool, args, timeout_s):
        calls.append((machine, tool, args, timeout_s))
        return SimpleNamespace(ok=True)

    monkeypatch.setattr(
        remote_session_ops, "call_remote_worker_tool", fake_call
    )
    monkeypatch.setattr(
        remote_session_ops,
        "_remote_result_data",
        lambda result, *, tool, machine: {
            "result": result,
            "tool": tool,
            "machine": machine,
        },
    )

    result = await remote_session_ops.end_worker_session(
        machine="worker-a",
        worker_session_id="WORKER12",
        timeout_s=30,
    )

    assert calls == [
        (
            "worker-a",
            "session_end",
            {"session_id": "WORKER12"},
            30,
        )
    ]
    assert result["tool"] == "session_end"


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
        prepared = store.require_session(session_id)
        assert prepared.session_id == session.session_id
        assert prepared.termination_requested_at is not None
        return ["job_one"]

    async def fake_stop_owned_shells(session_id: str) -> list[str]:
        assert session_id == session.session_id
        return ["shell_one"]

    monkeypatch.setattr(session_ops, "_stop_owned_jobs", fake_stop_owned_jobs)
    monkeypatch.setattr(
        session_ops, "_stop_owned_shells", fake_stop_owned_shells
    )

    result = await session_ops.session_end_execute(session.session_id)

    assert calls == [session.session_id]
    assert result.ended is True
    assert result.stopped_jobs == ["job_one"]
    assert result.stopped_shells == ["shell_one"]
    with pytest.raises(ValueError, match="unknown session_id"):
        store.require_session(session.session_id)


@pytest.mark.asyncio
async def test_stop_owned_jobs_reports_only_stopped_or_terminal_jobs(
    monkeypatch,
):
    jobs = [
        SimpleNamespace(job_id="killed"),
        SimpleNamespace(job_id="finished"),
        SimpleNamespace(job_id="running"),
    ]
    calls: list[tuple[str, bool]] = []

    async def fake_list(session_id: str, include_finished: bool):
        calls.append((session_id, include_finished))
        return SimpleNamespace(jobs=jobs)

    async def fake_stop(session_id: str, job_id: str):
        status = "succeeded" if job_id == "finished" else "running"
        return SimpleNamespace(
            killed=job_id == "killed",
            job=SimpleNamespace(status=status),
        )

    monkeypatch.setattr(
        "local_shell_mcp.jobs.runtime.job_list_execute", fake_list
    )
    monkeypatch.setattr(
        "local_shell_mcp.jobs.runtime.job_stop_execute", fake_stop
    )

    assert await session_ops._stop_owned_jobs("SESSION1") == [
        "killed",
        "finished",
    ]
    assert calls == [("SESSION1", False)]


@pytest.mark.asyncio
async def test_stop_owned_shells_kills_only_matching_owner(monkeypatch):
    listed: list[str] = []
    killed: list[str] = []

    async def fake_list(session_id: str):
        listed.append(session_id)
        return ["owned"]

    async def fake_kill(shell_id: str):
        killed.append(shell_id)
        return SimpleNamespace(killed=True)

    monkeypatch.setattr(
        "local_shell_mcp.ops.shell.list_owned_persistent_shell_ids_execute",
        fake_list,
    )
    monkeypatch.setattr(
        "local_shell_mcp.ops.shell.kill_persistent_shell_execute", fake_kill
    )

    assert await session_ops._stop_owned_shells("SESSION1") == ["owned"]
    assert listed == ["SESSION1"]
    assert killed == ["owned"]


@pytest.mark.asyncio
async def test_session_end_waits_for_in_flight_job_admission(monkeypatch):
    job_entered = asyncio.Event()
    release_job = asyncio.Event()
    end_entered = asyncio.Event()

    async def fake_job_start(*_args, **_kwargs):
        job_entered.set()
        await release_job.wait()
        return SimpleNamespace(job_id="job_one")

    async def fake_session_end(session_id: str):
        end_entered.set()
        return SimpleNamespace(session_id=session_id, ended=True)

    monkeypatch.setattr(
        jobs_runtime, "_job_start_execute_unlocked", fake_job_start
    )
    monkeypatch.setattr(
        session_ops, "_session_end_execute_unlocked", fake_session_end
    )

    job_task = asyncio.create_task(
        jobs_runtime.job_start_execute("SESSION1", "echo ok")
    )
    await job_entered.wait()
    end_task = asyncio.create_task(session_ops.session_end_execute("SESSION1"))
    await asyncio.sleep(0)
    assert not end_entered.is_set()

    release_job.set()
    await job_task
    result = await end_task

    assert end_entered.is_set()
    assert result.ended is True


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
        prepared = store.require_session(remote_session.session_id)
        assert prepared.worker_session_id == session.worker_session_id
        assert prepared.termination_requested_at is not None
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


@pytest.mark.asyncio
async def test_expired_remote_session_end_can_still_release_worker_binding(
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
        expires_at=0,
    )
    calls: list[str] = []

    async def fake_stop_owned_jobs(session_id: str) -> list[str]:
        assert (
            store.require_session(session_id).termination_requested_at
            is not None
        )
        return []

    async def fake_remote_call(remote_session, tool, args):
        calls.append(remote_session.worker_session_id or "")
        assert tool == "session_end"
        assert args == {}
        return {"ended": True}

    monkeypatch.setattr(session_ops, "_stop_owned_jobs", fake_stop_owned_jobs)
    monkeypatch.setattr(
        "local_shell_mcp.ops.utils.remote_session.call_remote_session_tool",
        fake_remote_call,
    )

    result = await session_ops.session_end_execute(session.session_id)

    assert result.ended is True
    assert calls == ["WORKER12"]


@pytest.mark.asyncio
async def test_worker_dispatch_registers_session_end(monkeypatch):
    calls: list[str] = []

    async def fake_session_end(session_id: str):
        calls.append(session_id)
        return {"session_id": session_id, "ended": True}

    monkeypatch.setattr(session_ops, "session_end_execute", fake_session_end)

    result = await worker_dispatch._HANDLERS["session_end"](
        {"session_id": "WORKER12"}
    )

    assert calls == ["WORKER12"]
    assert result["ended"] is True


@pytest.mark.asyncio
async def test_session_end_registry_wrapper_delegates(monkeypatch):
    async def fake_session_end(session_id: str):
        return {"session_id": session_id, "ended": True}

    monkeypatch.setattr(
        session_registry, "session_end_execute", fake_session_end
    )

    result = await session_registry.session_end.func("SESSION1")

    assert result == {"session_id": "SESSION1", "ended": True}
