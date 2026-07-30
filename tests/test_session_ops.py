import asyncio
import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.jobs import runtime as jobs_runtime
from local_shell_mcp.ops import session as session_ops
from local_shell_mcp.ops import shell as shell_ops
from local_shell_mcp.ops.utils import remote_session as remote_session_ops
from local_shell_mcp.remote_worker import dispatch as worker_dispatch
from local_shell_mcp.tool_session.store import get_tool_session_store
from local_shell_mcp.tools.registry import session as session_registry


def _start_peer_managed_job_lease(
    job_id: str, marker, release
) -> subprocess.Popen[str]:
    script = f"""
import time
from pathlib import Path
from local_shell_mcp.utils.runtime_identity import ManagedJobLease

lease = ManagedJobLease({job_id!r})
lease.acquire()
Path({str(marker)!r}).write_text("live", encoding="utf-8")
while not Path({str(release)!r}).exists():
    time.sleep(0.01)
lease.release()
"""
    return subprocess.Popen(
        [sys.executable, "-c", script],
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_peer_marker(
    process: subprocess.Popen[str], marker, *, timeout_s: float = 5.0
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if marker.exists():
            return
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"peer lease process exited early\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )
        time.sleep(0.01)
    raise AssertionError("peer lease process did not acquire its lock")


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
async def test_session_start_reconciles_stale_shell_job_before_capacity_check(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AGENT_SESSIONS", "1")
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    stale_session = store.create_session(workdir=tmp_path, expires_at=0)
    jobs_runtime._save_store(
        {
            "version": jobs_runtime.JOB_STORE_VERSION,
            "jobs": [
                {
                    "kind": "shell",
                    "status": "running",
                    "job_id": "job_stale",
                    "session_id": stale_session.session_id,
                    "shell_id": "missing-shell",
                    "command": "sleep 60",
                    "cwd": str(tmp_path),
                    "created_at": 1.0,
                    "updated_at": 1.0,
                }
            ],
        }
    )

    async def empty_inventory():
        return set()

    monkeypatch.setattr(
        jobs_runtime,
        "authoritative_persistent_shell_ids_execute",
        empty_inventory,
    )

    result = await session_ops.session_start_execute(".")

    assert result.session_id != stale_session.session_id
    with pytest.raises(ValueError, match="unknown session_id"):
        store.require_session(stale_session.session_id)
    assert jobs_runtime._load_store()["jobs"][0]["status"] == "lost"


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
async def test_local_session_change_cwd_excludes_concurrent_teardown(
    tmp_path, monkeypatch
):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(workdir=first)
    change_started = asyncio.Event()
    release_change = asyncio.Event()
    teardown_started = asyncio.Event()

    async def blocking_to_thread(function, *args, **kwargs):
        assert function is session_ops._change_local_session_cwd
        change_started.set()
        await release_change.wait()
        return function(*args, **kwargs)

    async def fake_teardown(session_id: str, *, force: bool = False):
        assert session_id == session.session_id
        assert force is False
        teardown_started.set()
        return SimpleNamespace(ended=True)

    monkeypatch.setattr(session_ops.asyncio, "to_thread", blocking_to_thread)
    monkeypatch.setattr(
        session_ops, "_session_end_execute_unlocked", fake_teardown
    )

    change_task = asyncio.create_task(
        session_ops.session_change_cwd_execute(session.session_id, str(second))
    )
    await change_started.wait()
    end_task = asyncio.create_task(
        session_ops.session_end_execute(session.session_id)
    )
    await asyncio.sleep(0.05)

    assert not teardown_started.is_set()
    release_change.set()
    changed = await change_task
    ended = await end_task

    assert changed.workdir == str(second)
    assert ended.ended is True
    assert teardown_started.is_set()


@pytest.mark.asyncio
async def test_remote_session_change_cwd_excludes_concurrent_teardown(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(
        target="remote",
        workdir="remote-old",
        machine="worker-a",
        worker_session_id="WORKER12",
    )
    change_started = asyncio.Event()
    release_change = asyncio.Event()
    teardown_started = asyncio.Event()

    async def blocking_remote_change(remote_session, tool, args):
        assert remote_session.session_id == session.session_id
        assert tool == "session_change_cwd"
        assert args == {"workdir": "remote-new"}
        change_started.set()
        await release_change.wait()
        payload = session_ops._session_output(remote_session).model_dump(
            mode="json"
        )
        payload["workdir"] = "remote-new"
        return payload

    async def fake_teardown(session_id: str, *, force: bool = False):
        assert session_id == session.session_id
        assert force is False
        teardown_started.set()
        return SimpleNamespace(ended=True)

    monkeypatch.setattr(
        remote_session_ops,
        "call_remote_session_tool",
        blocking_remote_change,
    )
    monkeypatch.setattr(
        session_ops, "_session_end_execute_unlocked", fake_teardown
    )

    change_task = asyncio.create_task(
        session_ops.session_change_cwd_execute(session.session_id, "remote-new")
    )
    await change_started.wait()
    end_task = asyncio.create_task(
        session_ops.session_end_execute(session.session_id)
    )
    await asyncio.sleep(0.05)

    assert not teardown_started.is_set()
    release_change.set()
    changed = await change_task
    ended = await end_task

    assert changed.workdir == "remote-new"
    assert ended.ended is True
    assert teardown_started.is_set()


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
async def test_session_end_preserves_local_state_when_pty_cleanup_fails(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(workdir=tmp_path)
    store.register_persistent_shell(session.session_id, "shell_one")

    async def fake_stop_owned_jobs(_session_id: str) -> list[str]:
        return []

    async def failing_stop_owned_shells(_session_id: str) -> list[str]:
        raise RuntimeError("persistent shell could not be stopped")

    monkeypatch.setattr(session_ops, "_stop_owned_jobs", fake_stop_owned_jobs)
    monkeypatch.setattr(
        session_ops, "_stop_owned_shells", failing_stop_owned_shells
    )

    with pytest.raises(RuntimeError, match="could not be stopped"):
        await session_ops.session_end_execute(session.session_id)

    retained = store.require_session(session.session_id)
    assert retained.persistent_shell_ids == ("shell_one",)
    assert retained.termination_requested_at is not None


@pytest.mark.asyncio
async def test_destination_teardown_fails_closed_for_live_peer_managed_copy(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    source = store.create_session(workdir=tmp_path)
    destination = store.create_session(workdir=tmp_path)
    job_id = "job_peer_copy"
    marker = tmp_path / "peer-live"
    release = tmp_path / "release-peer"
    process = _start_peer_managed_job_lease(job_id, marker, release)

    async def no_shells(_session_id: str) -> list[str]:
        return []

    monkeypatch.setattr(session_ops, "_stop_owned_shells", no_shells)
    try:
        _wait_for_peer_marker(process, marker)
        jobs_runtime._save_store(
            {
                "version": jobs_runtime.JOB_STORE_VERSION,
                "jobs": [
                    {
                        "job_id": job_id,
                        "kind": "managed",
                        "managed_kind": "session-copy",
                        "managed_payload": {
                            "src_session_id": source.session_id,
                            "dst_session_id": destination.session_id,
                        },
                        "runtime_instance_id": "peer-runtime",
                        "managed_lease_version": 1,
                        "session_id": source.session_id,
                        "status": "running",
                        "created_at": time.time(),
                        "updated_at": time.time(),
                        "attempts": 1,
                    }
                ],
            }
        )

        with pytest.raises(
            RuntimeError, match="could not be confirmed stopped"
        ):
            await session_ops.session_end_execute(destination.session_id)

        retained = store.require_session(destination.session_id)
        assert retained.termination_requested_at is not None
        row = jobs_runtime._load_store()["jobs"][0]
        assert row["status"] == "running"

        release.write_text("release", encoding="utf-8")
        assert await asyncio.to_thread(process.wait, timeout=5) == 0

        ended = await session_ops.session_end_execute(destination.session_id)
        assert ended.ended is True
        with pytest.raises(ValueError, match="unknown session_id"):
            store.require_session(destination.session_id)
    finally:
        release.touch(exist_ok=True)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.asyncio
async def test_destination_teardown_migrates_legacy_managed_copy(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    source = store.create_session(workdir=tmp_path)
    destination = store.create_session(workdir=tmp_path)
    jobs_runtime._save_store(
        {
            "version": jobs_runtime.JOB_STORE_VERSION,
            "jobs": [
                {
                    "job_id": "job_legacy_copy",
                    "kind": "managed",
                    "managed_kind": "session-copy",
                    "managed_payload": {
                        "src_session_id": source.session_id,
                        "dst_session_id": destination.session_id,
                    },
                    "runtime_instance_id": "previous-runtime",
                    "session_id": source.session_id,
                    "status": "running",
                    "created_at": time.time(),
                    "updated_at": time.time(),
                    "attempts": 1,
                }
            ],
        }
    )

    async def no_shells(_session_id: str) -> list[str]:
        return []

    monkeypatch.setattr(session_ops, "_stop_owned_shells", no_shells)

    ended = await session_ops.session_end_execute(destination.session_id)

    assert ended.ended is True
    with pytest.raises(ValueError, match="unknown session_id"):
        store.require_session(destination.session_id)
    row = jobs_runtime._load_store()["jobs"][0]
    assert row["status"] == "lost"


@pytest.mark.asyncio
async def test_session_end_retry_rechecks_lost_job_before_deleting_session(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(workdir=tmp_path)
    stop_calls = 0

    async def fake_list(_session_id: str, include_finished: bool):
        assert include_finished is True
        return SimpleNamespace(
            jobs=[SimpleNamespace(job_id="job_one", status="lost")]
        )

    async def fake_stop(_session_id: str, _job_id: str):
        nonlocal stop_calls
        stop_calls += 1
        status = "lost" if stop_calls == 1 else "stopped"
        return SimpleNamespace(
            killed=False,
            job=SimpleNamespace(status=status),
        )

    async def fake_stop_references(*_args, **_kwargs):
        return []

    async def no_shells(_session_id: str):
        return []

    monkeypatch.setattr(
        "local_shell_mcp.jobs.runtime._job_list_execute_unlocked", fake_list
    )
    monkeypatch.setattr(
        "local_shell_mcp.jobs.runtime._job_stop_execute_unlocked", fake_stop
    )
    monkeypatch.setattr(
        "local_shell_mcp.jobs.runtime.job_stop_managed_references_execute",
        fake_stop_references,
    )
    monkeypatch.setattr(session_ops, "_stop_owned_shells", no_shells)

    with pytest.raises(RuntimeError, match="status='lost'"):
        await session_ops.session_end_execute(session.session_id)

    retained = store.require_session(session.session_id)
    assert retained.termination_requested_at is not None

    result = await session_ops.session_end_execute(session.session_id)

    assert result.ended is True
    assert result.stopped_jobs == ["job_one"]
    assert stop_calls == 2
    with pytest.raises(ValueError, match="unknown session_id"):
        store.require_session(session.session_id)


@pytest.mark.asyncio
async def test_stop_owned_jobs_reports_only_stopped_or_terminal_jobs(
    monkeypatch,
):
    jobs = [
        SimpleNamespace(job_id="killed", status="running"),
        SimpleNamespace(job_id="finished", status="succeeded"),
        SimpleNamespace(job_id="stopped", status="stopped"),
    ]
    calls: list[tuple[str, bool]] = []

    async def fake_list(session_id: str, include_finished: bool):
        calls.append((session_id, include_finished))
        return SimpleNamespace(jobs=jobs)

    async def fake_stop(session_id: str, job_id: str):
        assert job_id == "killed"
        return SimpleNamespace(
            killed=job_id == "killed",
            job=SimpleNamespace(status="running"),
        )

    async def fake_stop_references(
        referenced_session_id: str, *, managed_kind: str, payload_key: str
    ) -> list[str]:
        assert referenced_session_id == "SESSION1"
        assert managed_kind == "session-copy"
        assert payload_key == "dst_session_id"
        return ["target-copy"]

    monkeypatch.setattr(
        "local_shell_mcp.jobs.runtime._job_list_execute_unlocked", fake_list
    )
    monkeypatch.setattr(
        "local_shell_mcp.jobs.runtime._job_stop_execute_unlocked", fake_stop
    )
    monkeypatch.setattr(
        "local_shell_mcp.jobs.runtime.job_stop_managed_references_execute",
        fake_stop_references,
    )

    assert await session_ops._stop_owned_jobs("SESSION1") == [
        "killed",
        "target-copy",
    ]
    assert calls == [("SESSION1", True)]


@pytest.mark.asyncio
async def test_stop_owned_jobs_consumes_durable_completion_without_inventory(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(workdir=tmp_path)
    paths = jobs_runtime._attempt_paths("job_completed", 1)
    paths["status"].write_text(
        json.dumps(
            {
                "exit_code": 0,
                "completed_at": 5.0,
                "error": None,
                "log_truncated": False,
                "output_bytes": 0,
            }
        ),
        encoding="utf-8",
    )
    jobs_runtime._save_store(
        {
            "version": jobs_runtime.JOB_STORE_VERSION,
            "jobs": [
                {
                    "job_id": "job_completed",
                    "kind": "shell",
                    "name": "completed",
                    "status": "running",
                    "command": "echo done",
                    "cwd": str(tmp_path),
                    "session_id": session.session_id,
                    "shell_id": "shell_completed",
                    "status_path": str(paths["status"]),
                    "created_at": 1.0,
                    "updated_at": 2.0,
                    "attempts": 1,
                }
            ],
        }
    )

    async def uncertain_inventory():
        return None

    async def unexpected_stop(_session_id: str, _job_id: str):
        raise AssertionError("durably completed job must not be stopped")

    monkeypatch.setattr(
        jobs_runtime,
        "authoritative_persistent_shell_ids_execute",
        uncertain_inventory,
    )
    monkeypatch.setattr(jobs_runtime, "job_stop_execute", unexpected_stop)

    assert await session_ops._stop_owned_jobs(session.session_id) == []
    assert jobs_runtime._load_store()["jobs"][0]["status"] == "succeeded"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "starting", "stopping", "lost"])
async def test_stop_owned_jobs_rejects_unconfirmed_stop(status, monkeypatch):
    async def fake_list(_session_id: str, include_finished: bool):
        assert include_finished is True
        return SimpleNamespace(
            jobs=[SimpleNamespace(job_id="job_one", status=status)]
        )

    async def fake_stop(_session_id: str, _job_id: str):
        return SimpleNamespace(killed=False, job=SimpleNamespace(status=status))

    async def unexpected_references(*_args, **_kwargs):
        raise AssertionError(
            "reference cleanup must not run after an ambiguous stop"
        )

    monkeypatch.setattr(
        "local_shell_mcp.jobs.runtime._job_list_execute_unlocked", fake_list
    )
    monkeypatch.setattr(
        "local_shell_mcp.jobs.runtime._job_stop_execute_unlocked", fake_stop
    )
    monkeypatch.setattr(
        "local_shell_mcp.jobs.runtime.job_stop_managed_references_execute",
        unexpected_references,
    )

    with pytest.raises(RuntimeError, match=f"status='{status}'"):
        await session_ops._stop_owned_jobs("SESSION1")


@pytest.mark.asyncio
async def test_stop_owned_shells_rejects_unknown_owner_inventory(monkeypatch):
    async def fake_inventory():
        return SimpleNamespace(shells=[])

    async def uncertain_owned(_session_id: str):
        return None

    monkeypatch.setattr(
        "local_shell_mcp.ops.shell.list_persistent_shells_execute",
        fake_inventory,
    )
    monkeypatch.setattr(
        "local_shell_mcp.ops.shell.list_owned_persistent_shell_ids_execute",
        uncertain_owned,
    )
    monkeypatch.setattr(
        session_ops,
        "get_tool_session_store",
        lambda: SimpleNamespace(
            require_session=lambda _session_id: SimpleNamespace(
                persistent_shell_ids=()
            )
        ),
    )

    with pytest.raises(RuntimeError, match="ownership could not be determined"):
        await session_ops._stop_owned_shells("SESSION1")


@pytest.mark.asyncio
async def test_session_end_preserves_peer_owned_conpty_shell(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(workdir=tmp_path)
    store.register_persistent_shell(session.session_id, "peer-conpty")

    monkeypatch.setattr(
        shell_ops, "_use_conpty_persistent_shell_backend", lambda: True
    )

    async def no_local_owned_shells(_owner_session_id: str):
        return []

    monkeypatch.setattr(
        shell_ops.conpty, "list_owned_shell_ids", no_local_owned_shells
    )
    peer_lease = shell_ops.conpty._ConPtyShellLease("peer-conpty")
    peer_lease.acquire()
    try:
        with pytest.raises(
            RuntimeError, match="ownership could not be determined"
        ):
            await session_ops.session_end_execute(session.session_id)

        retained = store.require_session(session.session_id)
        assert retained.persistent_shell_ids == ("peer-conpty",)
        assert retained.termination_requested_at is not None
    finally:
        peer_lease.release()


@pytest.mark.asyncio
async def test_session_end_retries_unconfirmed_conpty_termination(
    tmp_path, monkeypatch
):
    class CloseOncePty:
        exitstatus = None

        def __init__(self) -> None:
            self.alive = True
            self.close_calls = 0

        def isalive(self) -> bool:
            return self.alive

        def read(self, _size=None) -> str:
            time.sleep(0.01)
            return ""

        def close(self, force=False) -> None:
            _ = force
            self.close_calls += 1
            if self.close_calls == 1:
                raise OSError("close failed")
            self.alive = False
            self.exitstatus = 0

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(workdir=tmp_path)
    process = CloseOncePty()
    conpty = shell_ops.conpty
    conpty.reset_conpty_sessions_for_tests()
    monkeypatch.setattr(
        shell_ops, "_use_conpty_persistent_shell_backend", lambda: True
    )
    monkeypatch.setattr(conpty, "is_available", lambda: True)
    monkeypatch.setattr(conpty, "_shell_executable", lambda: "cmd.exe")
    monkeypatch.setattr(conpty, "_spawn_pty", lambda *_args: process)
    monkeypatch.setattr(conpty, "relative_display", lambda path: str(path))
    monkeypatch.setattr(conpty, "audit", lambda *_args, **_kwargs: None)

    await conpty.start_shell(
        shell_id="owned-conpty",
        cwd=tmp_path,
        command=None,
        owner_session_id=session.session_id,
    )
    store.register_persistent_shell(session.session_id, "owned-conpty")
    try:
        with pytest.raises(RuntimeError, match="could not be stopped"):
            await session_ops.session_end_execute(session.session_id)

        retained = store.require_session(session.session_id)
        assert retained.persistent_shell_ids == ("owned-conpty",)
        assert retained.termination_requested_at is not None
        assert conpty.has_session("owned-conpty") is True
        assert conpty.authoritative_shell_ids() == {"owned-conpty"}

        ended = await session_ops.session_end_execute(session.session_id)

        assert ended.session_id == session.session_id
        assert ended.stopped_shells == ["owned-conpty"]
        assert conpty.has_session("owned-conpty") is False
        assert conpty.authoritative_shell_ids() == set()
        assert process.close_calls == 2
    finally:
        if conpty.has_session("owned-conpty"):
            await conpty.kill_shell("owned-conpty")


@pytest.mark.asyncio
async def test_stop_owned_shells_kills_only_matching_owner(monkeypatch):
    listed: list[str] = []
    killed: list[str] = []
    reconciled: list[tuple[str, set[str]]] = []

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
    monkeypatch.setattr(
        session_ops,
        "get_tool_session_store",
        lambda: SimpleNamespace(
            reconcile_session_persistent_shells=lambda session_id, shell_ids: (
                reconciled.append((session_id, shell_ids))
            )
        ),
    )

    assert await session_ops._stop_owned_shells("SESSION1") == ["owned"]
    assert listed == ["SESSION1", "SESSION1"]
    assert killed == ["owned"]
    assert reconciled == [("SESSION1", {"owned"})]


@pytest.mark.asyncio
async def test_stop_owned_shells_accepts_shell_that_exits_during_kill(
    monkeypatch,
):
    async def fake_list(_session_id: str):
        return ["owned"]

    async def fake_kill(_shell_id: str):
        return SimpleNamespace(killed=False, stderr="session not found")

    async def authoritative_inventory():
        return set()

    monkeypatch.setattr(
        "local_shell_mcp.ops.shell.list_owned_persistent_shell_ids_execute",
        fake_list,
    )
    monkeypatch.setattr(
        "local_shell_mcp.ops.shell.kill_persistent_shell_execute", fake_kill
    )
    monkeypatch.setattr(
        "local_shell_mcp.ops.shell.authoritative_persistent_shell_ids_execute",
        authoritative_inventory,
    )
    monkeypatch.setattr(
        session_ops,
        "get_tool_session_store",
        lambda: SimpleNamespace(
            reconcile_session_persistent_shells=lambda *_args: None
        ),
    )

    assert await session_ops._stop_owned_shells("SESSION1") == ["owned"]


@pytest.mark.asyncio
@pytest.mark.parametrize("active_shell_ids", [None, {"owned"}])
async def test_stop_owned_shells_rejects_unconfirmed_failed_kill(
    monkeypatch, active_shell_ids
):
    async def fake_list(_session_id: str):
        return ["owned"]

    async def fake_kill(_shell_id: str):
        return SimpleNamespace(killed=False, stderr="temporary backend failure")

    async def authoritative_inventory():
        return active_shell_ids

    monkeypatch.setattr(
        "local_shell_mcp.ops.shell.list_owned_persistent_shell_ids_execute",
        fake_list,
    )
    monkeypatch.setattr(
        "local_shell_mcp.ops.shell.kill_persistent_shell_execute", fake_kill
    )
    monkeypatch.setattr(
        "local_shell_mcp.ops.shell.authoritative_persistent_shell_ids_execute",
        authoritative_inventory,
    )
    monkeypatch.setattr(
        session_ops,
        "get_tool_session_store",
        lambda: SimpleNamespace(
            reconcile_session_persistent_shells=lambda *_args: None
        ),
    )

    with pytest.raises(RuntimeError, match="could not be stopped"):
        await session_ops._stop_owned_shells("SESSION1")


@pytest.mark.asyncio
async def test_stop_owned_shells_does_not_kill_reused_unowned_name(monkeypatch):
    killed: list[str] = []
    reconciled: list[tuple[str, set[str]]] = []

    async def no_owned_shells(_session_id: str):
        return []

    async def unexpected_kill(shell_id: str):
        killed.append(shell_id)
        raise AssertionError("an unowned reused shell must not be killed")

    monkeypatch.setattr(
        "local_shell_mcp.ops.shell.list_owned_persistent_shell_ids_execute",
        no_owned_shells,
    )
    monkeypatch.setattr(
        "local_shell_mcp.ops.shell.kill_persistent_shell_execute",
        unexpected_kill,
    )
    monkeypatch.setattr(
        session_ops,
        "get_tool_session_store",
        lambda: SimpleNamespace(
            reconcile_session_persistent_shells=lambda session_id, shell_ids: (
                reconciled.append((session_id, shell_ids))
            )
        ),
    )

    assert await session_ops._stop_owned_shells("SESSION1") == []
    assert killed == []
    assert reconciled == [("SESSION1", set())]


@pytest.mark.asyncio
async def test_session_end_waits_for_in_flight_job_admission(monkeypatch):
    job_entered = asyncio.Event()
    release_job = asyncio.Event()
    end_entered = asyncio.Event()

    async def fake_job_start(*_args, **_kwargs):
        job_entered.set()
        await release_job.wait()
        return SimpleNamespace(job_id="job_one")

    async def fake_session_end(session_id: str, *, force: bool = False):
        assert force is False
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
    assert result.remote_cleanup_succeeded is True
    assert result.force_released is False
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
    assert result.remote_cleanup_succeeded is True
    assert result.force_released is False


@pytest.mark.asyncio
async def test_remote_session_force_release_survives_worker_failure(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AGENT_SESSIONS", "1")
    clear_settings_cache()
    store = get_tool_session_store()
    store.clear()
    session = store.create_session(
        target="remote",
        workdir="/remote/work",
        machine="worker-a",
        worker_session_id="WORKER12",
    )

    async def fake_stop_owned_jobs(_session_id: str) -> list[str]:
        return []

    async def failing_remote_call(_remote_session, _tool, _args):
        raise ConnectionError("worker offline")

    monkeypatch.setattr(session_ops, "_stop_owned_jobs", fake_stop_owned_jobs)
    monkeypatch.setattr(
        "local_shell_mcp.ops.utils.remote_session.call_remote_session_tool",
        failing_remote_call,
    )

    with pytest.raises(ConnectionError, match="worker offline"):
        await session_ops.session_end_execute(session.session_id)
    assert (
        store.require_session(session.session_id).termination_requested_at
        is not None
    )

    result = await session_ops.session_end_execute(
        session.session_id, force=True
    )

    assert result.ended is True
    assert result.remote_cleanup_succeeded is False
    assert result.force_released is True
    with pytest.raises(ValueError, match="unknown session_id"):
        store.require_session(session.session_id)
    replacement = store.create_session(workdir=tmp_path)
    assert replacement.target == "local"


@pytest.mark.asyncio
async def test_worker_dispatch_registers_session_end(monkeypatch):
    calls: list[str] = []

    async def fake_session_end(session_id: str, *, force: bool = False):
        calls.append(f"{session_id}:{force}")
        return {"session_id": session_id, "ended": True}

    monkeypatch.setattr(session_ops, "session_end_execute", fake_session_end)

    result = await worker_dispatch._HANDLERS["session_end"](
        {"session_id": "WORKER12", "force": True}
    )

    assert calls == ["WORKER12:True"]
    assert result["ended"] is True


@pytest.mark.asyncio
async def test_session_end_registry_wrapper_delegates(monkeypatch):
    async def fake_session_end(session_id: str, *, force: bool = False):
        return {"session_id": session_id, "ended": True, "force": force}

    monkeypatch.setattr(
        session_registry, "session_end_execute", fake_session_end
    )

    result = await session_registry.session_end.func("SESSION1", True)

    assert result["force"] is True
