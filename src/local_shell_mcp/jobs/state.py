"""Shared tracked-job row identity, operation, and projection helpers."""

import json
import time
import uuid
from typing import Any

from ..schemas.result_models.jobs import JobInfo
from ..utils.serialization import to_jsonable

ACTIVE_STATUSES = {"starting", "running", "stopping", "retrying"}
CONFIRMED_TERMINAL_STATUSES = {"succeeded", "failed", "exited", "stopped"}
MANAGED_STATE_MAX_BYTES = 262_144
_ACTIVE_JOB_OPERATIONS: set[str] = set()


def utc() -> float:
    """Return the current Unix timestamp."""
    return time.time()


def new_job_id() -> str:
    """Return one opaque durable job identifier."""
    return "job_" + uuid.uuid4().hex[:12]


def job_shell_id(job: dict[str, Any]) -> str:
    """Return one job's internal persistent-shell identifier."""
    value = job.get("shell_id")
    return str(value) if value else ""


def job_agent_session_id(job: dict[str, Any]) -> str | None:
    """Return the owning public agent-session id when present."""
    value = job.get("session_id")
    return value if isinstance(value, str) else None


def begin_job_operation(job: dict[str, Any], kind: str) -> str:
    """Publish one process-local operation token into a mutable durable row."""
    operation_id = f"{kind}_{uuid.uuid4().hex}"
    _ACTIVE_JOB_OPERATIONS.add(operation_id)
    job["operation_id"] = operation_id
    job["operation_kind"] = kind
    job["operation_started_at"] = utc()
    return operation_id


def job_operation_matches(job: dict[str, Any], operation_id: str) -> bool:
    """Return whether the row still contains one expected operation token."""
    return str(job.get("operation_id") or "") == operation_id


def job_operation_is_active(job: dict[str, Any], kind: str) -> bool:
    """Return whether a row operation is still owned by this process."""
    operation_id = str(job.get("operation_id") or "")
    return (
        bool(operation_id)
        and str(job.get("operation_kind") or "") == kind
        and operation_id in _ACTIVE_JOB_OPERATIONS
    )


def discard_job_operation(operation_id: str) -> None:
    """Forget one process-local operation token after its lifecycle ends."""
    _ACTIVE_JOB_OPERATIONS.discard(operation_id)


def clear_job_operation(job: dict[str, Any]) -> None:
    """Remove transient operation metadata from one durable row."""
    operation_id = str(job.get("operation_id") or "")
    if operation_id:
        discard_job_operation(operation_id)
    for key in ("operation_id", "operation_kind", "operation_started_at"):
        job.pop(key, None)


def public_job(job: dict[str, Any]) -> JobInfo:
    """Return typed public metadata without exposing shell or runtime paths."""
    return JobInfo.model_validate(
        {
            "job_id": str(job.get("job_id") or ""),
            "kind": str(job.get("kind") or "shell"),
            "name": str(job.get("name") or job.get("job_id") or ""),
            "status": str(job.get("status") or "unknown"),
            "command": str(job.get("command") or ""),
            "cwd": str(job.get("cwd") or "."),
            "session_id": str(job.get("session_id") or ""),
            "progress": job.get("progress"),
            "result": job.get("result"),
            "created_at": float(job.get("created_at") or 0),
            "updated_at": float(job.get("updated_at") or 0),
            "last_started_at": (
                float(job["last_started_at"])
                if job.get("last_started_at") is not None
                else None
            ),
            "completed_at": (
                float(job["completed_at"])
                if job.get("completed_at") is not None
                else None
            ),
            "exit_code": (
                int(job["exit_code"])
                if job.get("exit_code") is not None
                else None
            ),
            "error": str(job["error"])
            if job.get("error") is not None
            else None,
            "log_truncated": bool(job.get("log_truncated", False)),
            "output_bytes": int(job.get("output_bytes") or 0),
            "attempts": int(job.get("attempts") or 1),
        }
    )


def session_jobs(
    jobs: list[dict[str, Any]], session_id: str
) -> list[dict[str, Any]]:
    """Return rows owned by one public agent session."""
    return [row for row in jobs if job_agent_session_id(row) == session_id]


def find_session_job(
    store: dict[str, Any], session_id: str, job_id: str
) -> dict[str, Any]:
    """Return one durable row owned by the requested public session."""
    for row in store.get("jobs", []):
        if (
            row.get("job_id") == job_id
            and job_agent_session_id(row) == session_id
        ):
            return row
    raise KeyError(f"job not found in session: {job_id}")


def managed_json_dict(value: Any, *, label: str) -> dict[str, Any]:
    """Normalize and bound one managed-job payload, progress, or result object."""
    normalized = to_jsonable(value)
    if not isinstance(normalized, dict):
        raise TypeError(f"managed job {label} must be a JSON object")
    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MANAGED_STATE_MAX_BYTES:
        raise ValueError(
            f"managed job {label} exceeds {MANAGED_STATE_MAX_BYTES} bytes"
        )
    return normalized
