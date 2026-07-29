import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.jobs import runtime as jobs_ops
from local_shell_mcp.schemas.result_models.jobs import (
    JobInfo,
    JobListOutput,
    JobOutput,
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
from local_shell_mcp.tools.ops import jobs as job_tool_ops
from tests.helpers import python_shell_command


def _create_session(workdir: str = ".") -> str:
    store = get_tool_session_store()
    return store.create_session(workdir=workdir).session_id


def test_runner_command_quotes_powershell_arguments():
    command = jobs_ops._runner_command(
        [
            r"C:\Program Files\Python\python.exe",
            "-m",
            "local_shell_mcp.main",
            "--status-file",
            r"C:\state dir\job's-status.json",
        ],
        "powershell.exe",
    )

    assert command == (
        "& 'C:\\Program Files\\Python\\python.exe' '-m' "
        "'local_shell_mcp.main' '--status-file' "
        "'C:\\state dir\\job''s-status.json'"
    )


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

    list_result = await job_tool_ops.job_execute(
        "ABC12345", include_finished=False
    )
    assert list_result.operation == "list"
    assert list_result.jobs == [job]
    assert list_result.counts == {"running": 1}
    assert calls == [("list", "ABC12345", False)]

    calls.clear()
    poll_result = await job_tool_ops.job_execute(
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
    cancel_result = await job_tool_ops.job_execute("ABC12345", cancel=["job_1"])
    assert cancel_result.operation == "cancel"
    assert cancel_result.cancelled[0].killed is True
    assert calls == [("cancel", "ABC12345", "job_1")]

    calls.clear()
    retry_result = await job_tool_ops.job_execute("ABC12345", retry=["job_1"])
    assert retry_result.operation == "retry"
    assert retry_result.retried[0].attempts == 2
    assert calls == [("retry", "ABC12345", "job_1")]


@pytest.mark.asyncio
async def test_job_execute_rejects_combined_actions():
    with pytest.raises(ValueError, match="list_jobs cannot be combined"):
        await job_tool_ops.job_execute(
            "ABC12345", list_jobs=True, poll=["job_1"]
        )

    with pytest.raises(ValueError, match="mutually exclusive"):
        await job_tool_ops.job_execute(
            "ABC12345", poll=["job_1"], cancel=["job_2"]
        )


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

    async def fake_start_shell(
        cwd: str,
        name: str | None,
        command: str | None,
        *,
        owner_session_id: str | None = None,
    ):
        assert owner_session_id == session_id
        nonlocal session_counter
        session_counter += 1
        shell_id = f"shell_{session_counter}"
        active_sessions.add(shell_id)
        return StartPersistentShellOutput.model_validate(
            {
                "shell_id": shell_id,
                "name": name,
                "cwd": cwd,
                "command": command,
                "backend": "fake",
            }
        )

    async def fake_list_shells():
        return ListPersistentShellsOutput.model_validate(
            {"shells": [{"shell_id": shell_id} for shell_id in active_sessions]}
        )

    async def fake_read_shell(shell_id: str, lines: int):
        return ReadPersistentShellOutput(
            shell_id=shell_id, output=f"tail {shell_id}\n", lines=lines
        )

    async def fake_kill_shell(shell_id: str):
        active_sessions.discard(shell_id)
        return KillPersistentShellOutput(
            shell_id=shell_id, killed=True, stderr=""
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
    assert started.kind == "shell"

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

    async def fake_start_shell(
        cwd: str,
        name: str | None,
        command: str | None,
        *,
        owner_session_id: str | None = None,
    ):
        assert owner_session_id == first_session
        return StartPersistentShellOutput.model_validate(
            {"shell_id": f"shell-{name}", "name": name, "cwd": cwd}
        )

    async def fake_list_shells():
        return ListPersistentShellsOutput.model_validate(
            {"shells": [{"shell_id": "shell-first-job"}]}
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
async def test_tracked_job_is_lost_when_shell_disappears_without_status(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session_id = _create_session()

    async def fake_start_shell(
        cwd: str,
        name: str | None,
        command: str | None,
        *,
        owner_session_id: str | None = None,
    ):
        assert owner_session_id == session_id
        return StartPersistentShellOutput(
            shell_id="missing-shell", name=name, cwd=cwd, command=command
        )

    async def fake_list_shells():
        return ListPersistentShellsOutput(shells=[])

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
    assert listed.jobs[0].status == "lost"
    assert listed.jobs[0].session_id == session_id
    assert listed.counts == {"lost": 1}


def _configure_job_state(tmp_path, monkeypatch, **overrides):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    for name, value in overrides.items():
        monkeypatch.setenv(f"LOCAL_SHELL_MCP_{name.upper()}", str(value))
    clear_settings_cache()
    get_tool_session_store().clear()


def test_job_runner_persists_bounded_output_and_terminal_status(
    tmp_path, monkeypatch
):
    _configure_job_state(tmp_path, monkeypatch)
    paths = jobs_ops._attempt_paths("job_runner", 1)
    command = (
        "echo prefix-" + "x" * 100 + "-suffix"
        if os.name == "nt"
        else python_shell_command("print('prefix-' + 'x' * 100 + '-suffix')")
    )
    paths["command"].write_text(command, encoding="utf-8")
    args = SimpleNamespace(
        command_file=str(paths["command"]),
        log_file=str(paths["log"]),
        status_file=str(paths["status"]),
        cwd=str(tmp_path),
        shell=os.environ.get("COMSPEC", "cmd.exe")
        if os.name == "nt"
        else "/bin/bash",
        max_log_bytes=32,
    )

    with pytest.raises(SystemExit) as exit_info:
        jobs_ops.run_job_runner_from_args(args)

    status = json.loads(paths["status"].read_text(encoding="utf-8"))
    output = paths["log"].read_text(encoding="utf-8")
    assert exit_info.value.code == 0
    assert status["exit_code"] == 0
    assert status["error"] is None
    assert status["log_truncated"] is True
    assert status["output_bytes"] > len(output.encode())
    assert output.rstrip().endswith("-suffix")
    assert len(output.encode()) <= 32


def test_job_runner_records_nonzero_exit(tmp_path, monkeypatch):
    _configure_job_state(tmp_path, monkeypatch)
    paths = jobs_ops._attempt_paths("job_failed", 1)
    command = (
        "echo failed-output & exit /b 7"
        if os.name == "nt"
        else python_shell_command(
            "import sys; print('failed-output'); sys.exit(7)"
        )
    )
    paths["command"].write_text(command, encoding="utf-8")
    args = SimpleNamespace(
        command_file=str(paths["command"]),
        log_file=str(paths["log"]),
        status_file=str(paths["status"]),
        cwd=str(tmp_path),
        shell=os.environ.get("COMSPEC", "cmd.exe")
        if os.name == "nt"
        else "/bin/bash",
        max_log_bytes=1024,
    )

    with pytest.raises(SystemExit) as exit_info:
        jobs_ops.run_job_runner_from_args(args)

    status = json.loads(paths["status"].read_text(encoding="utf-8"))
    output_lines = paths["log"].read_text(encoding="utf-8").splitlines()
    assert exit_info.value.code == 7
    assert status["exit_code"] == 7
    assert status["error"] is None
    assert [line.rstrip() for line in output_lines] == ["failed-output"]


@pytest.mark.asyncio
async def test_terminal_job_output_remains_available_after_shell_exit(
    tmp_path, monkeypatch
):
    _configure_job_state(tmp_path, monkeypatch)
    session_id = _create_session()
    paths = jobs_ops._attempt_paths("job_done", 1)
    paths["log"].write_text("durable output\n", encoding="utf-8")
    paths["status"].write_text(
        json.dumps(
            {
                "exit_code": 0,
                "completed_at": 5.0,
                "error": None,
                "log_truncated": False,
                "output_bytes": 15,
            }
        ),
        encoding="utf-8",
    )
    jobs_ops._save_store(
        {
            "version": jobs_ops.JOB_STORE_VERSION,
            "jobs": [
                {
                    "job_id": "job_done",
                    "name": "done",
                    "status": "running",
                    "command": "echo durable output",
                    "cwd": str(tmp_path),
                    "session_id": session_id,
                    "shell_id": "gone-shell",
                    "log_path": str(paths["log"]),
                    "status_path": str(paths["status"]),
                    "created_at": 1.0,
                    "updated_at": 2.0,
                    "last_started_at": 2.0,
                    "attempts": 1,
                }
            ],
        }
    )

    async def no_shells():
        return ListPersistentShellsOutput(shells=[])

    monkeypatch.setattr(jobs_ops, "list_persistent_shells_execute", no_shells)

    result = await jobs_ops.job_tail_execute(session_id, "job_done", lines=20)

    assert result.job.status == "succeeded"
    assert result.job.exit_code == 0
    assert result.job.completed_at == 5.0
    assert result.output == "durable output\n"
    assert result.message == "job completed with exit code 0"


def test_job_store_recovers_from_backup_and_migrates_v1(tmp_path, monkeypatch):
    _configure_job_state(tmp_path, monkeypatch)
    jobs_ops._job_store_path().parent.mkdir(parents=True, exist_ok=True)
    jobs_ops._job_store_path().write_text("{broken", encoding="utf-8")
    jobs_ops._job_store_backup_path().write_text(
        json.dumps(
            {
                "version": 1,
                "jobs": [
                    {
                        "job_id": "legacy",
                        "status": "stopped",
                        "session_id": "ABC12345",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    store = jobs_ops._load_store()

    assert store["version"] == jobs_ops.JOB_STORE_VERSION
    assert store["jobs"][0]["job_id"] == "legacy"


def test_job_store_refuses_to_reset_when_main_and_backup_are_corrupt(
    tmp_path, monkeypatch
):
    _configure_job_state(tmp_path, monkeypatch)
    jobs_ops._job_store_path().parent.mkdir(parents=True, exist_ok=True)
    jobs_ops._job_store_path().write_text("{broken", encoding="utf-8")
    jobs_ops._job_store_backup_path().write_text("[]", encoding="utf-8")

    with pytest.raises(RuntimeError, match="refusing to reset"):
        jobs_ops._load_store()


def test_job_store_retention_keeps_active_and_newest_finished(
    tmp_path, monkeypatch
):
    _configure_job_state(tmp_path, monkeypatch, max_jobs=2)
    old_paths = jobs_ops._attempt_paths("old", 1)
    new_paths = jobs_ops._attempt_paths("new", 1)
    for path in [*old_paths.values(), *new_paths.values()]:
        path.write_text("artifact", encoding="utf-8")
    store = {
        "version": jobs_ops.JOB_STORE_VERSION,
        "jobs": [
            {
                "job_id": "active",
                "status": "running",
                "created_at": 1.0,
                "updated_at": 1.0,
            },
            {
                "job_id": "old",
                "status": "failed",
                "created_at": 2.0,
                "updated_at": 2.0,
            },
            {
                "job_id": "new",
                "status": "succeeded",
                "created_at": 3.0,
                "updated_at": 3.0,
            },
        ],
    }

    jobs_ops._save_store(store)
    persisted = jobs_ops._load_store()

    assert {row["job_id"] for row in persisted["jobs"]} == {"active", "new"}
    assert not any(path.exists() for path in old_paths.values())
    assert all(path.exists() for path in new_paths.values())


@pytest.mark.asyncio
async def test_job_start_failure_is_persisted_as_failed(tmp_path, monkeypatch):
    _configure_job_state(tmp_path, monkeypatch)
    session_id = _create_session()

    async def fail_start(
        cwd: str,
        name: str | None,
        command: str | None,
        *,
        owner_session_id: str | None = None,
    ):
        assert owner_session_id == session_id
        raise RuntimeError("tmux unavailable")

    monkeypatch.setattr(jobs_ops, "start_persistent_shell_execute", fail_start)

    with pytest.raises(RuntimeError, match="tmux unavailable"):
        await jobs_ops.job_start_execute(session_id, "echo hello")

    rows = jobs_ops._load_store()["jobs"]
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["completed_at"] is not None
    assert rows[0]["error"] == "start failed: RuntimeError: tmux unavailable"


@pytest.mark.asyncio
async def test_interrupted_start_recovers_active_shell(tmp_path, monkeypatch):
    _configure_job_state(tmp_path, monkeypatch)
    session_id = _create_session()
    jobs_ops._save_store(
        {
            "version": jobs_ops.JOB_STORE_VERSION,
            "jobs": [
                {
                    "job_id": "recover",
                    "name": "recover",
                    "status": "starting",
                    "command": "sleep 1",
                    "cwd": str(tmp_path),
                    "session_id": session_id,
                    "shell_id": "recover-shell",
                    "created_at": 1.0,
                    "updated_at": 1.0,
                    "last_started_at": None,
                    "attempts": 1,
                    "operation_id": "stale-start",
                    "operation_kind": "start",
                }
            ],
        }
    )

    async def active_shell():
        return ListPersistentShellsOutput.model_validate(
            {"shells": [{"shell_id": "recover-shell"}]}
        )

    monkeypatch.setattr(
        jobs_ops, "list_persistent_shells_execute", active_shell
    )

    result = await jobs_ops.job_list_execute(session_id)

    assert result.jobs[0].status == "running"
    assert result.jobs[0].last_started_at is not None
    assert "recovered job start" in (result.jobs[0].error or "")


@pytest.mark.asyncio
async def test_job_retry_failure_is_persisted_and_clears_pending_state(
    tmp_path, monkeypatch
):
    _configure_job_state(tmp_path, monkeypatch)
    session_id = _create_session()
    jobs_ops._save_store(
        {
            "version": jobs_ops.JOB_STORE_VERSION,
            "jobs": [
                {
                    "job_id": "retry-failure",
                    "name": "retry-failure",
                    "status": "failed",
                    "command": "echo retry",
                    "cwd": str(tmp_path),
                    "session_id": session_id,
                    "created_at": 1.0,
                    "updated_at": 2.0,
                    "last_started_at": 1.0,
                    "completed_at": 2.0,
                    "attempts": 1,
                }
            ],
        }
    )

    async def no_shells():
        return ListPersistentShellsOutput(shells=[])

    async def fail_start(
        cwd: str,
        name: str | None,
        command: str | None,
        *,
        owner_session_id: str | None = None,
    ):
        assert owner_session_id == session_id
        raise RuntimeError("retry shell unavailable")

    monkeypatch.setattr(jobs_ops, "list_persistent_shells_execute", no_shells)
    monkeypatch.setattr(jobs_ops, "start_persistent_shell_execute", fail_start)

    with pytest.raises(RuntimeError, match="retry shell unavailable"):
        await jobs_ops.job_retry_execute(session_id, "retry-failure")

    job = jobs_ops._load_store()["jobs"][0]
    assert job["status"] == "failed"
    assert job["attempts"] == 2
    assert job["completed_at"] is not None
    assert job["error"] == (
        "retry failed: RuntimeError: retry shell unavailable"
    )
    assert not any(key.startswith("pending_") for key in job)
    assert "operation_id" not in job


@pytest.mark.asyncio
async def test_interrupted_retry_adopts_active_pending_attempt(
    tmp_path, monkeypatch
):
    _configure_job_state(tmp_path, monkeypatch)
    session_id = _create_session()
    paths = jobs_ops._attempt_paths("retry-recover", 2)
    jobs_ops._save_store(
        {
            "version": jobs_ops.JOB_STORE_VERSION,
            "jobs": [
                {
                    "job_id": "retry-recover",
                    "name": "retry-recover",
                    "status": "retrying",
                    "command": "sleep 1",
                    "cwd": str(tmp_path),
                    "session_id": session_id,
                    "shell_id": "old-shell",
                    "created_at": 1.0,
                    "updated_at": 2.0,
                    "last_started_at": 1.0,
                    "attempts": 1,
                    "pending_attempt": 2,
                    "pending_shell_id": "retry-shell",
                    "pending_command_path": str(paths["command"]),
                    "pending_log_path": str(paths["log"]),
                    "pending_status_path": str(paths["status"]),
                    "operation_id": "stale-retry",
                    "operation_kind": "retry",
                }
            ],
        }
    )

    async def active_shell():
        return ListPersistentShellsOutput.model_validate(
            {"shells": [{"shell_id": "retry-shell"}]}
        )

    monkeypatch.setattr(
        jobs_ops, "list_persistent_shells_execute", active_shell
    )

    result = await jobs_ops.job_list_execute(session_id)

    recovered = result.jobs[0]
    assert recovered.status == "running"
    assert recovered.attempts == 2
    assert recovered.last_started_at is not None
    assert "recovered retry" in (recovered.error or "")
    job = jobs_ops._load_store()["jobs"][0]
    assert job["shell_id"] == "retry-shell"
    assert job["log_path"] == str(paths["log"])
    assert not any(key.startswith("pending_") for key in job)
    assert "operation_id" not in job


def test_concurrent_job_store_transactions_do_not_lose_records(
    tmp_path, monkeypatch
):
    _configure_job_state(tmp_path, monkeypatch, max_jobs=100)

    def append(index: int) -> None:
        with jobs_ops._store_transaction() as store:
            store["jobs"].append(
                {
                    "job_id": f"job-{index}",
                    "status": "succeeded",
                    "created_at": float(index),
                    "updated_at": float(index),
                }
            )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(append, range(32)))

    persisted = jobs_ops._load_store()["jobs"]
    assert {row["job_id"] for row in persisted} == {
        f"job-{index}" for index in range(32)
    }


@pytest.mark.asyncio
async def test_job_start_does_not_launch_shell_for_invalid_store(
    tmp_path, monkeypatch
):
    _configure_job_state(tmp_path, monkeypatch)
    session_id = _create_session()
    invalid = json.dumps({"version": 99, "jobs": []})
    jobs_ops._job_store_path().parent.mkdir(parents=True, exist_ok=True)
    jobs_ops._job_store_path().write_text(invalid, encoding="utf-8")
    jobs_ops._job_store_backup_path().write_text(invalid, encoding="utf-8")
    started = False

    async def fake_start(
        cwd: str,
        name: str | None,
        command: str | None,
        *,
        owner_session_id: str | None = None,
    ):
        assert owner_session_id == session_id
        nonlocal started
        started = True
        return StartPersistentShellOutput(
            shell_id="must-not-start", name=name, cwd=cwd, command=command
        )

    monkeypatch.setattr(jobs_ops, "start_persistent_shell_execute", fake_start)

    with pytest.raises(RuntimeError, match="refusing to reset"):
        await jobs_ops.job_start_execute(session_id, "echo must-not-run")

    assert started is False
    runtime_dir = jobs_ops._job_runtime_dir()
    assert not list(runtime_dir.iterdir())


@pytest.mark.asyncio
async def test_job_start_kills_shell_when_running_state_cannot_be_committed(
    tmp_path, monkeypatch
):
    _configure_job_state(tmp_path, monkeypatch)
    session_id = _create_session()
    killed: list[str] = []

    async def corrupt_after_launch(
        cwd: str,
        name: str | None,
        command: str | None,
        *,
        owner_session_id: str | None = None,
    ):
        assert owner_session_id == session_id
        invalid = json.dumps({"version": 99, "jobs": []})
        jobs_ops._job_store_path().write_text(invalid, encoding="utf-8")
        jobs_ops._job_store_backup_path().write_text(invalid, encoding="utf-8")
        return StartPersistentShellOutput(
            shell_id="launched-shell", name=name, cwd=cwd, command=command
        )

    async def fake_kill(shell_id: str):
        killed.append(shell_id)
        return KillPersistentShellOutput(
            shell_id=shell_id, killed=True, stderr=""
        )

    monkeypatch.setattr(
        jobs_ops, "start_persistent_shell_execute", corrupt_after_launch
    )
    monkeypatch.setattr(jobs_ops, "kill_persistent_shell_execute", fake_kill)

    with pytest.raises(RuntimeError, match="refusing to reset"):
        await jobs_ops.job_start_execute(session_id, "echo launched")

    assert killed == ["launched-shell"]
    assert not list(jobs_ops._job_runtime_dir().iterdir())


@pytest.mark.asyncio
async def test_managed_job_tracks_progress_stop_retry_and_result(
    tmp_path, monkeypatch
):
    _configure_job_state(tmp_path, monkeypatch)
    jobs_ops.reset_managed_jobs_for_tests()
    session_id = _create_session()
    release = asyncio.Event()

    async def no_shells():
        return ListPersistentShellsOutput(shells=[])

    async def handler(context, payload):
        await context.log(f"started {payload['value']}")
        await context.update_progress(phase="waiting", value=payload["value"])
        await release.wait()
        await context.log("finished")
        return {"value": payload["value"]}

    monkeypatch.setattr(jobs_ops, "list_persistent_shells_execute", no_shells)
    jobs_ops.register_managed_job_handler("test-managed-lifecycle", handler)

    started = await jobs_ops.start_managed_job(
        session_id,
        "test-managed-lifecycle",
        {"value": 7},
        name="managed",
        command="managed test",
    )
    assert started.kind == "managed"
    assert started.status == "running"

    tailed = None
    for _ in range(100):
        await asyncio.sleep(0.01)
        tailed = await jobs_ops.job_tail_execute(session_id, started.job_id)
        if tailed.job.progress == {"phase": "waiting", "value": 7}:
            break
    assert tailed is not None
    assert "started 7" in tailed.output
    assert tailed.job.progress == {"phase": "waiting", "value": 7}

    stopped = await jobs_ops.job_stop_execute(session_id, started.job_id)
    assert stopped.killed is True
    assert stopped.job.status == "stopped"

    retried = await jobs_ops.job_retry_execute(session_id, started.job_id)
    assert retried.kind == "managed"
    assert retried.status == "running"
    assert retried.attempts == 2
    release.set()

    current = retried
    for _ in range(100):
        await asyncio.sleep(0.01)
        current = (await jobs_ops.job_list_execute(session_id)).jobs[0]
        if current.status == "succeeded":
            break
    assert current.status == "succeeded"
    assert current.result == {"value": 7}
    assert current.progress == {"phase": "waiting", "value": 7}
    jobs_ops.reset_managed_jobs_for_tests()


@pytest.mark.asyncio
async def test_managed_reference_stop_cancels_job_owned_by_source_session(
    tmp_path, monkeypatch
):
    _configure_job_state(tmp_path, monkeypatch)
    jobs_ops.reset_managed_jobs_for_tests()
    source_session_id = _create_session()
    destination_session_id = "DEST0001"
    entered = asyncio.Event()

    async def handler(_context, _payload):
        entered.set()
        await asyncio.Event().wait()

    jobs_ops.register_managed_job_handler("test-managed-reference", handler)
    started = await jobs_ops.start_managed_job(
        source_session_id,
        "test-managed-reference",
        {"dst_session_id": destination_session_id},
    )
    await entered.wait()

    stopped = await jobs_ops.job_stop_managed_references_execute(
        destination_session_id,
        managed_kind="test-managed-reference",
        payload_key="dst_session_id",
    )

    assert stopped == [started.job_id]
    current = (await jobs_ops.job_list_execute(source_session_id)).jobs[0]
    assert current.status == "stopped"
    assert jobs_ops._job_lifecycle_session_ids(
        source_session_id, started.job_id
    ) == tuple(sorted((source_session_id, destination_session_id)))
    jobs_ops.reset_managed_jobs_for_tests()


@pytest.mark.asyncio
async def test_managed_reference_stop_filters_unrelated_rows(monkeypatch):
    rows = [
        "not-a-row",
        {"kind": "shell", "status": "running"},
        {
            "kind": "managed",
            "managed_kind": "other",
            "status": "running",
        },
        {
            "kind": "managed",
            "managed_kind": "copy",
            "status": "stopped",
        },
        {
            "kind": "managed",
            "managed_kind": "copy",
            "status": "running",
            "managed_payload": None,
        },
        {
            "kind": "managed",
            "managed_kind": "copy",
            "status": "running",
            "managed_payload": {"dst_session_id": "OTHER"},
        },
        {
            "kind": "managed",
            "managed_kind": "copy",
            "status": "running",
            "managed_payload": {"dst_session_id": "DEST0001"},
            "session_id": "",
            "job_id": "missing-owner",
        },
        {
            "kind": "managed",
            "managed_kind": "copy",
            "status": "running",
            "managed_payload": {"dst_session_id": "DEST0001"},
            "session_id": "SOURCE01",
            "job_id": "job_target",
        },
    ]

    @contextmanager
    def fake_transaction():
        yield {"jobs": rows}

    async def fake_stop(session_id: str, job_id: str):
        assert (session_id, job_id) == ("SOURCE01", "job_target")
        return SimpleNamespace(
            killed=False, job=SimpleNamespace(status="succeeded")
        )

    monkeypatch.setattr(jobs_ops, "_store_transaction", fake_transaction)
    monkeypatch.setattr(
        jobs_ops, "_refresh_job_status", lambda row, _active: row
    )
    monkeypatch.setattr(
        jobs_ops, "_stop_managed_job_without_session_admission", fake_stop
    )

    assert await jobs_ops.job_stop_managed_references_execute(
        "DEST0001", managed_kind="copy", payload_key="dst_session_id"
    ) == ["job_target"]


def test_managed_job_validation_and_lost_recovery():
    async def first_handler(context, payload):  # noqa: ARG001
        return payload

    async def second_handler(context, payload):  # noqa: ARG001
        return payload

    with pytest.raises(ValueError, match="must not be empty"):
        jobs_ops.register_managed_job_handler("   ", first_handler)
    jobs_ops.register_managed_job_handler(
        "test-managed-validation", first_handler
    )
    jobs_ops.register_managed_job_handler(
        "test-managed-validation", first_handler
    )
    with pytest.raises(ValueError, match="already registered"):
        jobs_ops.register_managed_job_handler(
            "test-managed-validation", second_handler
        )

    running = jobs_ops._refresh_job_status(
        {
            "job_id": "job_managed_lost",
            "kind": "managed",
            "status": "running",
        },
        set(),
        now=10.0,
    )
    assert running["status"] == "lost"
    assert running["completed_at"] == 10.0
    assert "retry it" in running["error"]

    stopping = jobs_ops._refresh_job_status(
        {
            "job_id": "job_managed_stopping",
            "kind": "managed",
            "status": "stopping",
        },
        set(),
        now=11.0,
    )
    assert stopping["status"] == "stopped"
    assert stopping["error"] is None


@pytest.mark.asyncio
async def test_remote_job_companion_merges_controller_managed_and_worker_jobs(
    tmp_path, monkeypatch
):
    _configure_job_state(tmp_path, monkeypatch)
    jobs_ops.reset_managed_jobs_for_tests()
    store = get_tool_session_store()
    remote_session = store.create_session(
        target="remote",
        workdir="/remote/project",
        machine="worker-a",
        worker_session_id="WORKER01",
    )
    release = asyncio.Event()
    calls: list[dict] = []

    async def no_shells():
        return ListPersistentShellsOutput(shells=[])

    async def handler(context, payload):
        await context.update_progress(phase="waiting")
        await release.wait()
        return payload

    remote_job = _job_info("job_remote", remote_session.session_id)

    async def fake_remote_call(session, tool, args):
        assert session.session_id == remote_session.session_id
        assert tool == "job"
        calls.append(args)
        if args.get("list_jobs") or not any(
            args.get(name) is not None for name in ("poll", "cancel", "retry")
        ):
            return JobOutput(
                operation="list",
                jobs=[remote_job],
                counts={"running": 1},
            ).model_dump(mode="json")
        requested = args.get("poll") or []
        return JobOutput(
            operation="poll",
            outputs=[
                JobTailOutput(job=remote_job, output="remote output")
                for item in requested
                if item == remote_job.job_id
            ],
        ).model_dump(mode="json")

    monkeypatch.setattr(jobs_ops, "list_persistent_shells_execute", no_shells)
    monkeypatch.setattr(
        job_tool_ops, "call_remote_session_tool", fake_remote_call
    )
    jobs_ops.register_managed_job_handler("test-remote-managed", handler)
    managed = await jobs_ops.start_managed_job(
        remote_session.session_id,
        "test-remote-managed",
        {"source": "controller"},
    )

    listed = await job_tool_ops.job_execute(remote_session.session_id)
    assert [job.job_id for job in listed.jobs] == [
        managed.job_id,
        remote_job.job_id,
    ]
    assert listed.counts == {"running": 2}

    polled = await job_tool_ops.job_execute(
        remote_session.session_id,
        poll=[managed.job_id, remote_job.job_id],
        lines=7,
    )
    assert [row.job.job_id for row in polled.outputs] == [
        managed.job_id,
        remote_job.job_id,
    ]
    assert calls[-1]["poll"] == [remote_job.job_id]

    before = len(calls)
    cancelled = await job_tool_ops.job_execute(
        remote_session.session_id, cancel=[managed.job_id]
    )
    assert cancelled.cancelled[0].job.status == "stopped"
    assert len(calls) == before
    jobs_ops.reset_managed_jobs_for_tests()


@pytest.mark.asyncio
async def test_managed_job_failure_result_bounds_and_launch_rollback(
    tmp_path, monkeypatch
):
    _configure_job_state(tmp_path, monkeypatch)
    jobs_ops.reset_managed_jobs_for_tests()
    session_id = _create_session()

    async def no_shells():
        return ListPersistentShellsOutput(shells=[])

    async def failing_handler(context, payload):  # noqa: ARG001
        raise RuntimeError("managed failure")

    async def oversized_handler(context, payload):  # noqa: ARG001
        return {"value": "x" * (jobs_ops._MANAGED_STATE_MAX_BYTES + 1)}

    async def oversized_progress_handler(context, payload):  # noqa: ARG001
        await context.update_progress(
            value="x" * (jobs_ops._MANAGED_STATE_MAX_BYTES + 1)
        )
        return payload

    async def idle_handler(context, payload):  # noqa: ARG001
        return payload

    monkeypatch.setattr(jobs_ops, "list_persistent_shells_execute", no_shells)
    jobs_ops.register_managed_job_handler(
        "test-managed-failure", failing_handler
    )
    failed = await jobs_ops.start_managed_job(
        session_id, "test-managed-failure", {}
    )
    current = failed
    for _ in range(100):
        await asyncio.sleep(0.01)
        current = (await jobs_ops.job_list_execute(session_id)).jobs[0]
        if current.status == "failed":
            break
    assert current.status == "failed"
    assert current.exit_code == 1
    assert current.error == "RuntimeError: managed failure"
    assert (
        "managed failure"
        in (await jobs_ops.job_tail_execute(session_id, failed.job_id)).output
    )

    jobs_ops.register_managed_job_handler(
        "test-managed-oversized-result", oversized_handler
    )
    oversized = await jobs_ops.start_managed_job(
        session_id, "test-managed-oversized-result", {}
    )
    oversized_row = oversized
    for _ in range(100):
        await asyncio.sleep(0.01)
        rows = await jobs_ops.job_list_execute(session_id)
        oversized_row = next(
            row for row in rows.jobs if row.job_id == oversized.job_id
        )
        if oversized_row.status == "failed":
            break
    assert oversized_row.status == "failed"
    assert "managed job result exceeds" in str(oversized_row.error)

    jobs_ops.register_managed_job_handler(
        "test-managed-oversized-progress", oversized_progress_handler
    )
    progress_job = await jobs_ops.start_managed_job(
        session_id, "test-managed-oversized-progress", {}
    )
    progress_row = progress_job
    for _ in range(100):
        await asyncio.sleep(0.01)
        rows = await jobs_ops.job_list_execute(session_id)
        progress_row = next(
            row for row in rows.jobs if row.job_id == progress_job.job_id
        )
        if progress_row.status == "failed":
            break
    assert progress_row.status == "failed"
    assert "managed job progress exceeds" in str(progress_row.error)

    jobs_ops.register_managed_job_handler(
        "test-managed-payload-bound", idle_handler
    )
    with pytest.raises(ValueError, match="managed job payload exceeds"):
        await jobs_ops.start_managed_job(
            session_id,
            "test-managed-payload-bound",
            {"value": "x" * (jobs_ops._MANAGED_STATE_MAX_BYTES + 1)},
        )
    jobs_ops.register_managed_job_handler(
        "test-managed-launch-failure", idle_handler
    )

    def fail_launch(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("launch failed")

    monkeypatch.setattr(jobs_ops, "_launch_managed_job", fail_launch)
    before = {
        row.job_id for row in (await jobs_ops.job_list_execute(session_id)).jobs
    }
    with pytest.raises(RuntimeError, match="launch failed"):
        await jobs_ops.start_managed_job(
            session_id, "test-managed-launch-failure", {}
        )
    after = {
        row.job_id for row in (await jobs_ops.job_list_execute(session_id)).jobs
    }
    assert after == before
    runtime_files = {
        path.name
        for path in jobs_ops._job_runtime_dir().glob("*-attempt-1.log")
    }
    assert runtime_files == {
        f"{failed.job_id}-attempt-1.log",
        f"{oversized.job_id}-attempt-1.log",
        f"{progress_job.job_id}-attempt-1.log",
    }
    jobs_ops.reset_managed_jobs_for_tests()


@pytest.mark.asyncio
async def test_remote_job_list_keeps_controller_jobs_when_worker_is_offline(
    tmp_path, monkeypatch
):
    _configure_job_state(tmp_path, monkeypatch)
    jobs_ops.reset_managed_jobs_for_tests()
    store = get_tool_session_store()
    remote_session = store.create_session(
        target="remote",
        workdir="/remote/project",
        machine="worker-a",
        worker_session_id="WORKER01",
    )
    release = asyncio.Event()

    async def handler(context, payload):
        await context.update_progress(phase="waiting")
        await release.wait()
        return payload

    async def offline(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("worker offline")

    jobs_ops.register_managed_job_handler("test-offline-managed", handler)
    managed = await jobs_ops.start_managed_job(
        remote_session.session_id, "test-offline-managed", {"value": 1}
    )
    monkeypatch.setattr(job_tool_ops, "call_remote_session_tool", offline)

    listed = await job_tool_ops.job_execute(remote_session.session_id)
    assert [row.job_id for row in listed.jobs] == [managed.job_id]
    assert listed.counts == {"running": 1}
    assert listed.message is not None and "worker offline" in listed.message

    polled = await job_tool_ops.job_execute(
        remote_session.session_id, poll=[managed.job_id]
    )
    assert polled.outputs[0].job.job_id == managed.job_id
    cancelled = await job_tool_ops.job_execute(
        remote_session.session_id, cancel=[managed.job_id]
    )
    assert cancelled.cancelled[0].job.status == "stopped"
    jobs_ops.reset_managed_jobs_for_tests()


@pytest.mark.asyncio
async def test_managed_actions_do_not_query_shell_inventory(
    tmp_path, monkeypatch
):
    _configure_job_state(tmp_path, monkeypatch)
    jobs_ops.reset_managed_jobs_for_tests()
    session_id = _create_session()
    release = asyncio.Event()

    async def handler(context, payload):
        await context.update_progress(phase="waiting")
        await release.wait()
        return payload

    jobs_ops.register_managed_job_handler("test-no-shell-inventory", handler)
    started = await jobs_ops.start_managed_job(
        session_id,
        "test-no-shell-inventory",
        {"value": 9},
    )

    async def fail_inventory():
        raise AssertionError("managed action queried shell inventory")

    monkeypatch.setattr(
        jobs_ops, "list_persistent_shells_execute", fail_inventory
    )

    tailed = await jobs_ops.job_tail_execute(session_id, started.job_id)
    for _ in range(100):
        if tailed.job.progress == {"phase": "waiting"}:
            break
        await asyncio.sleep(0.01)
        tailed = await jobs_ops.job_tail_execute(session_id, started.job_id)
    assert tailed.job.progress == {"phase": "waiting"}

    stopped = await jobs_ops.job_stop_execute(session_id, started.job_id)
    assert stopped.job.status == "stopped"

    retried = await jobs_ops.job_retry_execute(session_id, started.job_id)
    assert retried.status == "running"
    release.set()

    completed = await jobs_ops.job_tail_execute(session_id, started.job_id)
    for _ in range(100):
        if completed.job.status == "succeeded":
            break
        await asyncio.sleep(0.01)
        completed = await jobs_ops.job_tail_execute(session_id, started.job_id)
    assert completed.job.status == "succeeded"
    assert completed.job.result == {"value": 9}
    jobs_ops.reset_managed_jobs_for_tests()
