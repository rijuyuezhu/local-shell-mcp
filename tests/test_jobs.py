import pytest

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.ops import jobs as jobs_ops
from local_shell_mcp.schemas.result_models.shell import (
    KillPersistentShellOutput,
    ListPersistentShellsOutput,
    ReadPersistentShellOutput,
    StartPersistentShellOutput,
)


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
