import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

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

    async def fake_start_shell(cwd: str, name: str | None, command: str | None):
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
    paths["command"].write_text(
        "python3 -c \"print('prefix-' + 'x' * 100 + '-suffix')\"",
        encoding="utf-8",
    )
    args = SimpleNamespace(
        command_file=str(paths["command"]),
        log_file=str(paths["log"]),
        status_file=str(paths["status"]),
        cwd=str(tmp_path),
        shell="/bin/bash",
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
    assert output.endswith("-suffix\n")
    assert len(output.encode()) <= 32


def test_job_runner_records_nonzero_exit(tmp_path, monkeypatch):
    _configure_job_state(tmp_path, monkeypatch)
    paths = jobs_ops._attempt_paths("job_failed", 1)
    paths["command"].write_text(
        "printf 'failed-output\\n'; exit 7", encoding="utf-8"
    )
    args = SimpleNamespace(
        command_file=str(paths["command"]),
        log_file=str(paths["log"]),
        status_file=str(paths["status"]),
        cwd=str(tmp_path),
        shell="/bin/bash",
        max_log_bytes=1024,
    )

    with pytest.raises(SystemExit) as exit_info:
        jobs_ops.run_job_runner_from_args(args)

    status = json.loads(paths["status"].read_text(encoding="utf-8"))
    assert exit_info.value.code == 7
    assert status["exit_code"] == 7
    assert status["error"] is None
    assert paths["log"].read_text(encoding="utf-8") == "failed-output\n"


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

    async def fail_start(cwd: str, name: str | None, command: str | None):
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

    async def fail_start(cwd: str, name: str | None, command: str | None):
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

    async def fake_start(cwd: str, name: str | None, command: str | None):
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
        cwd: str, name: str | None, command: str | None
    ):
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
