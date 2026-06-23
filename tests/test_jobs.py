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


def _job_info(job_id: str = "job_1") -> JobInfo:
    return JobInfo(
        job_id=job_id,
        name=job_id,
        status="running",
        command="echo ok",
        cwd=".",
        session_id=f"session_{job_id}",
        backend="fake",
        created_at=1.0,
        updated_at=1.0,
        last_started_at=1.0,
        attempts=1,
    )


@pytest.mark.asyncio
async def test_job_execute_dispatches_companion_actions(monkeypatch):
    calls = []
    job = _job_info()

    async def fake_list(include_finished=True):
        calls.append(("list", include_finished))
        return JobListOutput(jobs=[job], counts={"running": 1})

    async def fake_tail(job_id: str, lines: int):
        calls.append(("poll", job_id, lines))
        return JobTailOutput(job=job, output=f"{job_id}:{lines}")

    async def fake_stop(job_id: str):
        calls.append(("cancel", job_id))
        return JobStopOutput(job=job, killed=True, stderr="")

    async def fake_retry(job_id: str):
        calls.append(("retry", job_id))
        data = job.model_dump()
        data.update(job_id=job_id, attempts=2)
        return JobRetryOutput.model_validate(data)

    monkeypatch.setattr(jobs_ops, "job_list_execute", fake_list)
    monkeypatch.setattr(jobs_ops, "job_tail_execute", fake_tail)
    monkeypatch.setattr(jobs_ops, "job_stop_execute", fake_stop)
    monkeypatch.setattr(jobs_ops, "job_retry_execute", fake_retry)

    list_result = await jobs_ops.job_execute(include_finished=False)
    assert list_result.operation == "list"
    assert list_result.jobs == [job]
    assert list_result.counts == {"running": 1}
    assert calls == [("list", False)]

    calls.clear()
    poll_result = await jobs_ops.job_execute(poll=["job_1", "job_2"], lines=5)
    assert poll_result.operation == "poll"
    assert [entry.output for entry in poll_result.outputs] == [
        "job_1:5",
        "job_2:5",
    ]
    assert calls == [("poll", "job_1", 5), ("poll", "job_2", 5)]

    calls.clear()
    cancel_result = await jobs_ops.job_execute(cancel=["job_1"])
    assert cancel_result.operation == "cancel"
    assert cancel_result.cancelled[0].killed is True
    assert calls == [("cancel", "job_1")]

    calls.clear()
    retry_result = await jobs_ops.job_execute(retry=["job_1"])
    assert retry_result.operation == "retry"
    assert retry_result.retried[0].attempts == 2
    assert calls == [("retry", "job_1")]


@pytest.mark.asyncio
async def test_job_execute_rejects_combined_actions():
    with pytest.raises(ValueError, match="list_jobs cannot be combined"):
        await jobs_ops.job_execute(list_jobs=True, poll=["job_1"])

    with pytest.raises(ValueError, match="mutually exclusive"):
        await jobs_ops.job_execute(poll=["job_1"], cancel=["job_2"])


@pytest.mark.asyncio
async def test_tracked_job_lifecycle_with_backing_shells(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()

    active_sessions: set[str] = set()
    session_counter = 0

    async def fake_start_shell(cwd: str, name: str | None, command: str | None):
        nonlocal session_counter
        session_counter += 1
        session_id = f"sess_{session_counter}"
        active_sessions.add(session_id)
        return StartPersistentShellOutput.model_validate(
            {
                "session_id": session_id,
                "name": name,
                "cwd": cwd,
                "command": command,
                "backend": "fake",
            }
        )

    async def fake_list_shells():
        return ListPersistentShellsOutput(
            sessions=[
                {"session_id": session_id} for session_id in active_sessions
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
        "python -m http.server", ".", "serve"
    )

    assert started.name == "serve"
    assert started.status == "running"
    assert started.attempts == 1

    listed = await jobs_ops.job_list_execute()
    assert listed.counts == {"running": 1}
    assert listed.jobs[0].job_id == started.job_id

    tailed = await jobs_ops.job_tail_execute(started.job_id, lines=5)
    assert tailed.output == "tail sess_1\n"
    assert tailed.job.status == "running"

    stopped = await jobs_ops.job_stop_execute(started.job_id)
    assert stopped.killed is True
    assert stopped.job.status == "stopped"

    running_only = await jobs_ops.job_list_execute(include_finished=False)
    assert running_only.jobs == []
    assert running_only.counts == {"stopped": 1}

    retried = await jobs_ops.job_retry_execute(started.job_id)
    assert retried.status == "running"
    assert retried.attempts == 2
    assert retried.session_id == "sess_2"


@pytest.mark.asyncio
async def test_tracked_job_running_status_exits_when_shell_disappears(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()

    async def fake_start_shell(cwd: str, name: str | None, command: str | None):
        return StartPersistentShellOutput(
            session_id="missing-session", name=name, cwd=cwd, command=command
        )

    async def fake_list_shells():
        return ListPersistentShellsOutput(sessions=[])

    monkeypatch.setattr(
        jobs_ops, "start_persistent_shell_execute", fake_start_shell
    )
    monkeypatch.setattr(
        jobs_ops, "list_persistent_shells_execute", fake_list_shells
    )

    started = await jobs_ops.job_start_execute("echo done", ".", None)
    listed = await jobs_ops.job_list_execute()

    assert listed.jobs[0].job_id == started.job_id
    assert listed.jobs[0].status == "exited"
    assert listed.counts == {"exited": 1}
