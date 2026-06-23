import pytest

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.ops import jobs as jobs_ops
from local_shell_mcp.schemas.result_models.jobs import (
    JobInfo,
    JobListOutput,
    JobRetryOutput,
    JobStopOutput,
    JobTailOutput,
)
from local_shell_mcp.schemas.result_models.shell import (
    KillPersistentShellOutput,
    ListPersistentShellsOutput,
    ReadPersistentShellOutput,
    StartPersistentShellOutput,
)
from local_shell_mcp.tool_session.store import get_tool_session_store


def _create_session(workdir: str = ".") -> str:
    store = get_tool_session_store()
    return store.create_session(workdir=workdir).session_id


def _job_info(job_id: str = "job_1", session_id: str = "ABC12345") -> JobInfo:
    return JobInfo(
        job_id=job_id,
        name=job_id,
        status="running",
        command="echo ok",
        cwd=".",
        session_id=session_id,
        created_at=1.0,
        updated_at=1.0,
        last_started_at=1.0,
        attempts=1,
    )


@pytest.mark.asyncio
async def test_job_execute_dispatches_companion_actions(monkeypatch):
    calls = []
    job = _job_info()

    async def fake_list(session_id: str, include_finished=True):
        calls.append(("list", session_id, include_finished))
        return JobListOutput(jobs=[job], counts={"running": 1})

    async def fake_tail(session_id: str, job_id: str, lines: int):
        calls.append(("poll", session_id, job_id, lines))
        return JobTailOutput(job=job, output=f"{job_id}:{lines}")

    async def fake_stop(session_id: str, job_id: str):
        calls.append(("cancel", session_id, job_id))
        return JobStopOutput(job=job, killed=True, stderr="")

    async def fake_retry(session_id: str, job_id: str):
        calls.append(("retry", session_id, job_id))
        data = job.model_dump()
        data.update(job_id=job_id, attempts=2)
        return JobRetryOutput.model_validate(data)

    monkeypatch.setattr(jobs_ops, "job_list_execute", fake_list)
    monkeypatch.setattr(jobs_ops, "job_tail_execute", fake_tail)
    monkeypatch.setattr(jobs_ops, "job_stop_execute", fake_stop)
    monkeypatch.setattr(jobs_ops, "job_retry_execute", fake_retry)

    list_result = await jobs_ops.job_execute("ABC12345", include_finished=False)
    assert list_result.operation == "list"
    assert list_result.jobs == [job]
    assert list_result.counts == {"running": 1}
    assert calls == [("list", "ABC12345", False)]

    calls.clear()
    poll_result = await jobs_ops.job_execute(
        "ABC12345", poll=["job_1", "job_2"], lines=5
    )
    assert poll_result.operation == "poll"
    assert [entry.output for entry in poll_result.outputs] == [
        "job_1:5",
        "job_2:5",
    ]
    assert calls == [
        ("poll", "ABC12345", "job_1", 5),
        ("poll", "ABC12345", "job_2", 5),
    ]

    calls.clear()
    cancel_result = await jobs_ops.job_execute("ABC12345", cancel=["job_1"])
    assert cancel_result.operation == "cancel"
    assert cancel_result.cancelled[0].killed is True
    assert calls == [("cancel", "ABC12345", "job_1")]

    calls.clear()
    retry_result = await jobs_ops.job_execute("ABC12345", retry=["job_1"])
    assert retry_result.operation == "retry"
    assert retry_result.retried[0].attempts == 2
    assert calls == [("retry", "ABC12345", "job_1")]


@pytest.mark.asyncio
async def test_job_execute_rejects_combined_actions():
    with pytest.raises(ValueError, match="list_jobs cannot be combined"):
        await jobs_ops.job_execute("ABC12345", list_jobs=True, poll=["job_1"])

    with pytest.raises(ValueError, match="mutually exclusive"):
        await jobs_ops.job_execute("ABC12345", poll=["job_1"], cancel=["job_2"])


@pytest.mark.asyncio
async def test_tracked_job_lifecycle_with_backing_shells(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session_id = _create_session()

    active_sessions: set[str] = set()
    session_counter = 0

    async def fake_start_shell(cwd: str, name: str | None, command: str | None):
        nonlocal session_counter
        session_counter += 1
        shell_session_id = f"shell_{session_counter}"
        active_sessions.add(shell_session_id)
        return StartPersistentShellOutput.model_validate(
            {
                "session_id": shell_session_id,
                "name": name,
                "cwd": cwd,
                "command": command,
                "backend": "fake",
            }
        )

    async def fake_list_shells():
        return ListPersistentShellsOutput(
            sessions=[
                {"session_id": shell_session_id}
                for shell_session_id in active_sessions
            ]
        )

    async def fake_read_shell(session_id: str, lines: int):
        return ReadPersistentShellOutput(
            session_id=session_id, output=f"tail {session_id}\n", lines=lines
        )

    async def fake_kill_shell(session_id: str):
        active_sessions.discard(session_id)
        return KillPersistentShellOutput(
            session_id=session_id, killed=True, stderr=""
        )

    monkeypatch.setattr(
        jobs_ops, "start_persistent_shell_execute", fake_start_shell
    )
    monkeypatch.setattr(
        jobs_ops, "list_persistent_shells_execute", fake_list_shells
    )
    monkeypatch.setattr(
        jobs_ops, "read_persistent_shell_output_execute", fake_read_shell
    )
    monkeypatch.setattr(
        jobs_ops, "kill_persistent_shell_execute", fake_kill_shell
    )

    started = await jobs_ops.job_start_execute(
        session_id, "python -m http.server", ".", "serve"
    )

    assert started.name == "serve"
    assert started.status == "running"
    assert started.session_id == session_id
    assert started.cwd == str(tmp_path)
    assert started.attempts == 1
    assert "backend" not in started.model_dump()

    listed = await jobs_ops.job_list_execute(session_id)
    assert listed.counts == {"running": 1}
    assert listed.jobs[0].job_id == started.job_id
    assert listed.jobs[0].session_id == session_id

    tailed = await jobs_ops.job_tail_execute(
        session_id, started.job_id, lines=5
    )
    assert tailed.output == "tail shell_1\n"
    assert tailed.job.status == "running"
    assert tailed.job.session_id == session_id

    stopped = await jobs_ops.job_stop_execute(session_id, started.job_id)
    assert stopped.killed is True
    assert stopped.job.status == "stopped"

    running_only = await jobs_ops.job_list_execute(
        session_id, include_finished=False
    )
    assert running_only.jobs == []
    assert running_only.counts == {"stopped": 1}

    retried = await jobs_ops.job_retry_execute(session_id, started.job_id)
    assert retried.status == "running"
    assert retried.attempts == 2
    assert retried.session_id == session_id


@pytest.mark.asyncio
async def test_tracked_jobs_are_isolated_by_agent_session(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    first_session = _create_session()
    second_session = _create_session()

    async def fake_start_shell(cwd: str, name: str | None, command: str | None):
        return StartPersistentShellOutput.model_validate(
            {"session_id": f"shell-{name}", "name": name, "cwd": cwd}
        )

    async def fake_list_shells():
        return ListPersistentShellsOutput(
            sessions=[{"session_id": "shell-first-job"}]
        )

    monkeypatch.setattr(
        jobs_ops, "start_persistent_shell_execute", fake_start_shell
    )
    monkeypatch.setattr(
        jobs_ops, "list_persistent_shells_execute", fake_list_shells
    )

    started = await jobs_ops.job_start_execute(
        first_session, "sleep 60", ".", "first-job"
    )

    first_list = await jobs_ops.job_list_execute(first_session)
    second_list = await jobs_ops.job_list_execute(second_session)

    assert [job.job_id for job in first_list.jobs] == [started.job_id]
    assert second_list.jobs == []
    assert second_list.counts == {}

    with pytest.raises(KeyError, match="job not found in session"):
        await jobs_ops.job_tail_execute(second_session, started.job_id)
    with pytest.raises(KeyError, match="job not found in session"):
        await jobs_ops.job_stop_execute(second_session, started.job_id)
    with pytest.raises(KeyError, match="job not found in session"):
        await jobs_ops.job_retry_execute(second_session, started.job_id)


@pytest.mark.asyncio
async def test_tracked_job_running_status_exits_when_shell_disappears(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session_id = _create_session()

    async def fake_start_shell(cwd: str, name: str | None, command: str | None):
        return StartPersistentShellOutput(
            session_id="missing-shell", name=name, cwd=cwd, command=command
        )

    async def fake_list_shells():
        return ListPersistentShellsOutput(sessions=[])

    monkeypatch.setattr(
        jobs_ops, "start_persistent_shell_execute", fake_start_shell
    )
    monkeypatch.setattr(
        jobs_ops, "list_persistent_shells_execute", fake_list_shells
    )

    started = await jobs_ops.job_start_execute(
        session_id, "echo done", ".", None
    )
    listed = await jobs_ops.job_list_execute(session_id)

    assert listed.jobs[0].job_id == started.job_id
    assert listed.jobs[0].status == "exited"
    assert listed.jobs[0].session_id == session_id
    assert listed.counts == {"exited": 1}
