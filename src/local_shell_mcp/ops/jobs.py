"""Tracked persistent-shell command operation helpers."""

import contextlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from ..audit import audit
from ..config.settings import get_settings
from ..schemas.result_models.jobs import (
    JobInfo,
    JobListOutput,
    JobRetryOutput,
    JobStartOutput,
    JobStopOutput,
    JobTailOutput,
)
from .shell import (
    kill_persistent_shell_execute,
    list_persistent_shells_execute,
    read_persistent_shell_output_execute,
    start_persistent_shell_execute,
)

JOB_STORE_FILE_NAME = "jobs.json"
JOB_STORE_VERSION = 1
TERMINAL_STATUSES = {"exited", "stopped", "lost"}


def _utc() -> float:
    """Return current Unix timestamp."""
    return time.time()


def _job_store_path() -> Path:
    """Return the persisted tracked-job metadata store path."""
    return get_settings().state_dir / JOB_STORE_FILE_NAME


def _empty_store() -> dict[str, Any]:
    return {"version": JOB_STORE_VERSION, "jobs": []}


def _load_store() -> dict[str, Any]:
    """Load tracked-job metadata, tolerating missing or corrupt stores."""
    path = _job_store_path()
    if not path.exists():
        return _empty_store()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_store()
    if not isinstance(data, dict):
        return _empty_store()
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        jobs = []
    return {
        "version": JOB_STORE_VERSION,
        "jobs": [job for job in jobs if isinstance(job, dict)],
    }


def _save_store(store: dict[str, Any]) -> None:
    """Persist tracked-job metadata atomically."""
    path = _job_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(
        json.dumps(store, indent=2, sort_keys=True), encoding="utf-8"
    )
    with contextlib.suppress(OSError):
        tmp_path.chmod(0o600)
    tmp_path.replace(path)


def _new_job_id() -> str:
    """Return a compact human-readable job id."""
    return "job_" + uuid.uuid4().hex[:12]


def _shell_safe_name(value: str) -> str:
    """Return a stable persistent-shell session name derived from a job name."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "-", value.strip())
    return cleaned[:48] or "job"


def _active_session_ids(shells: Any) -> set[str]:
    """Extract active persistent shell ids from the shell list output."""
    data = shells.model_dump() if hasattr(shells, "model_dump") else shells
    return {
        str(item.get("session_id"))
        for item in data.get("sessions", [])
        if item.get("session_id")
    }


def _refresh_job_status(
    job: dict[str, Any], active_sessions: set[str], now: float | None = None
) -> dict[str, Any]:
    """Mark running jobs as exited when their backing persistent shell is gone."""
    status = str(job.get("status") or "unknown")
    session_id = str(job.get("session_id") or "")
    if status == "running" and session_id not in active_sessions:
        job["status"] = "exited"
        job["updated_at"] = now or _utc()
    return job


def _public_job(job: dict[str, Any]) -> JobInfo:
    """Return typed public metadata for one stored tracked-job row."""
    return JobInfo.model_validate(
        {
            "job_id": job.get("job_id"),
            "name": job.get("name"),
            "status": job.get("status"),
            "command": job.get("command"),
            "cwd": job.get("cwd"),
            "session_id": job.get("session_id"),
            "backend": job.get("backend"),
            "created_at": job.get("created_at"),
            "updated_at": job.get("updated_at"),
            "last_started_at": job.get("last_started_at"),
            "attempts": job.get("attempts", 1),
        }
    )


def _find_job(store: dict[str, Any], job_id: str) -> dict[str, Any]:
    """Return a mutable stored job row by id."""
    for job in store.get("jobs", []):
        if job.get("job_id") == job_id:
            return job
    raise KeyError(f"job not found: {job_id}")


async def job_start_execute(
    command: str, cwd: str = ".", name: str | None = None
) -> JobStartOutput:
    """Start a tracked command backed by a persistent shell session."""
    job_id = _new_job_id()
    display_name = name or job_id
    shell_name = _shell_safe_name(f"{display_name}-{job_id}")
    shell = await start_persistent_shell_execute(cwd, shell_name, command)
    shell_data = shell.model_dump()
    now = _utc()
    job = {
        "job_id": job_id,
        "name": display_name,
        "status": "running",
        "command": command,
        "cwd": cwd,
        "session_id": shell_data["session_id"],
        "backend": shell_data.get("backend"),
        "created_at": now,
        "updated_at": now,
        "last_started_at": now,
        "attempts": 1,
    }
    store = _load_store()
    store["jobs"].append(job)
    _save_store(store)
    audit(
        "job_start",
        job_id=job_id,
        session=shell_data["session_id"],
        cwd=cwd,
        command=command,
    )
    return JobStartOutput.model_validate(_public_job(job).model_dump())


async def job_list_execute(include_finished: bool = True) -> JobListOutput:
    """List tracked persistent-shell commands and status counts."""
    store = _load_store()
    active = _active_session_ids(await list_persistent_shells_execute())
    now = _utc()
    jobs = [
        _refresh_job_status(job, active, now) for job in store.get("jobs", [])
    ]
    _save_store(store)
    rows = [
        _public_job(job)
        for job in jobs
        if include_finished or job.get("status") not in TERMINAL_STATUSES
    ]
    rows.sort(key=lambda item: item.created_at, reverse=True)
    counts: dict[str, int] = {}
    for job in jobs:
        status = str(job.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return JobListOutput(jobs=rows, counts=counts)


async def job_tail_execute(job_id: str, lines: int = 200) -> JobTailOutput:
    """Read recent output for a tracked command from its backing persistent shell."""
    store = _load_store()
    active = _active_session_ids(await list_persistent_shells_execute())
    job = _refresh_job_status(_find_job(store, job_id), active)
    _save_store(store)
    public = _public_job(job)
    if job.get("status") != "running":
        return JobTailOutput(
            job=public,
            output="",
            message="job is not running; shell output is no longer available",
        )
    try:
        tail = await read_persistent_shell_output_execute(
            str(job["session_id"]), lines
        )
    except Exception as exc:
        job["status"] = "lost"
        job["updated_at"] = _utc()
        _save_store(store)
        return JobTailOutput(job=_public_job(job), output="", message=str(exc))
    tail_data = tail.model_dump()
    return JobTailOutput(job=public, output=tail_data.get("output", ""))


async def job_stop_execute(job_id: str) -> JobStopOutput:
    """Stop one tracked command and its backing persistent shell session."""
    store = _load_store()
    active = _active_session_ids(await list_persistent_shells_execute())
    job = _refresh_job_status(_find_job(store, job_id), active)
    killed = False
    stderr = ""
    if job.get("status") == "running":
        result = await kill_persistent_shell_execute(str(job["session_id"]))
        data = result.model_dump()
        killed = bool(data.get("killed"))
        stderr = str(data.get("stderr") or "")
        job["status"] = "stopped" if killed else "lost"
        job["updated_at"] = _utc()
    _save_store(store)
    audit(
        "job_stop", job_id=job_id, session=job.get("session_id"), killed=killed
    )
    return JobStopOutput(job=_public_job(job), killed=killed, stderr=stderr)


async def job_retry_execute(job_id: str) -> JobRetryOutput:
    """Restart a terminal tracked command with its original command and cwd."""
    store = _load_store()
    active = _active_session_ids(await list_persistent_shells_execute())
    job = _refresh_job_status(_find_job(store, job_id), active)
    if job.get("status") == "running":
        raise RuntimeError(f"job is still running: {job_id}")
    attempts = int(job.get("attempts") or 1) + 1
    shell_name = _shell_safe_name(
        f"{job.get('name') or job_id}-{job_id}-{attempts}"
    )
    shell = await start_persistent_shell_execute(
        str(job.get("cwd") or "."), shell_name, str(job["command"])
    )
    shell_data = shell.model_dump()
    now = _utc()
    job.update(
        {
            "status": "running",
            "session_id": shell_data["session_id"],
            "backend": shell_data.get("backend"),
            "updated_at": now,
            "last_started_at": now,
            "attempts": attempts,
        }
    )
    _save_store(store)
    audit(
        "job_retry",
        job_id=job_id,
        session=shell_data["session_id"],
        attempts=attempts,
    )
    return JobRetryOutput.model_validate(_public_job(job).model_dump())
