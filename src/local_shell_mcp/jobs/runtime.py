"""Shared durable tracked-job runtime, persistence, and runner helpers."""

import asyncio
import contextlib
import json
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ..audit import audit
from ..config.settings import get_settings
from ..errors import public_error_type
from ..ops.shell import (
    authoritative_persistent_shell_ids_execute,
    check_command_policy,
    kill_persistent_shell_execute,
    read_persistent_shell_output_execute,
    start_persistent_shell_execute,
)
from ..schemas.result_models.jobs import (
    JobListOutput,
    JobOutput,
    JobRetryOutput,
    JobStartOutput,
    JobStopOutput,
    JobTailOutput,
)
from ..tool_session.lifecycle import (
    session_lifecycle_lock,
    session_lifecycle_locks,
)
from ..tool_session.store import (
    get_tool_session_store,
    resolve_session_path,
)
from ..utils.private_files import write_private_text
from ..utils.runtime_identity import (
    MANAGED_JOB_LEASE_VERSION,
    PROCESS_INSTANCE_ID,
    ManagedJobLease,
    managed_job_lease_state,
)
from . import persistence as job_persistence
from . import recovery as job_recovery
from .persistence import (
    JOB_STORE_VERSION as _JOB_STORE_VERSION,
)
from .persistence import (
    TERMINAL_STATUSES,
)
from .persistence import (
    attempt_paths as _attempt_paths,
)
from .persistence import (
    job_runtime_dir as _persistence_job_runtime_dir,
)
from .persistence import (
    job_store_backup_path as _persistence_job_store_backup_path,
)
from .persistence import (
    job_store_path as _persistence_job_store_path,
)
from .persistence import (
    prune_store as _prune_store,
)
from .persistence import (
    remove_attempt_files as _remove_attempt_files,
)
from .persistence import (
    remove_attempt_paths as _remove_attempt_paths,
)
from .runner import compact_log as _compact_log
from .runner import run_job_runner_from_args as _run_job_runner_from_args
from .state import (
    ACTIVE_STATUSES,
    CONFIRMED_TERMINAL_STATUSES,
)
from .state import (
    MANAGED_STATE_MAX_BYTES as _STATE_MANAGED_STATE_MAX_BYTES,
)
from .state import (
    begin_job_operation as _begin_job_operation,
)
from .state import (
    clear_job_operation as _clear_job_operation,
)
from .state import discard_job_operation as _discard_job_operation
from .state import (
    find_session_job as _find_session_job,
)
from .state import (
    job_agent_session_id as _job_agent_session_id,
)
from .state import (
    job_operation_is_active as _job_operation_is_active,
)
from .state import (
    job_operation_matches as _job_operation_matches,
)
from .state import (
    job_shell_id as _job_shell_id,
)
from .state import (
    managed_json_dict as _managed_json_dict,
)
from .state import (
    new_job_id as _new_job_id,
)
from .state import (
    public_job as _public_job,
)
from .state import (
    session_jobs as _session_jobs,
)
from .state import (
    utc as _utc,
)

JOB_STORE_VERSION = _JOB_STORE_VERSION
_MANAGED_STATE_MAX_BYTES = _STATE_MANAGED_STATE_MAX_BYTES
JOB_STORE_LOCK_TIMEOUT_S = job_recovery.JOB_STORE_LOCK_TIMEOUT_S
JOB_STORE_LOCK_RETRY_INTERVAL_S = job_recovery.JOB_STORE_LOCK_RETRY_INTERVAL_S
MANAGED_JOB_STORE_RETRY_ATTEMPTS = 2
MANAGED_DEFERRED_UPDATE_VERSION = job_recovery.MANAGED_DEFERRED_UPDATE_VERSION
MANAGED_DEFERRED_APPLIED_KEY = job_recovery.MANAGED_DEFERRED_APPLIED_KEY
MANAGED_DEFERRED_MAX_RECORD_BYTES = (
    job_recovery.MANAGED_DEFERRED_MAX_RECORD_BYTES
)
_JOB_STORE_THREAD_LOCK = job_recovery._JOB_STORE_THREAD_LOCK
_managed_deferred_update_dir = job_recovery.managed_deferred_update_dir
_next_managed_deferred_sequence = job_recovery.next_managed_deferred_sequence
_write_managed_deferred_update = job_recovery.write_managed_deferred_update
_read_managed_deferred_record = job_recovery.read_managed_deferred_record
_read_managed_deferred_updates = job_recovery.read_managed_deferred_updates
_apply_managed_update = job_recovery.apply_managed_update
_reconcile_managed_deferred_updates = (
    job_recovery.reconcile_managed_deferred_updates
)
_remove_managed_deferred_updates = job_recovery.remove_managed_deferred_updates
_job_store_busy_error = job_recovery.job_store_busy_error
_store_transaction = job_recovery.store_transaction
type ManagedJobHandler = Callable[
    [ManagedJobContext, dict[str, Any]], Awaitable[dict[str, Any] | None]
]
_MANAGED_JOB_HANDLERS: dict[str, ManagedJobHandler] = {}
_MANAGED_JOB_TASKS: dict[str, asyncio.Task[None]] = {}
_MANAGED_JOB_LEASES: dict[str, ManagedJobLease] = {}


def run_job_runner_from_args(args: Any) -> None:
    """Compatibility facade for the standalone durable attempt runner."""
    _run_job_runner_from_args(args)


def _job_store_path() -> Path:
    """Compatibility facade for the primary durable job-store path."""
    return _persistence_job_store_path()


def _job_store_backup_path() -> Path:
    """Compatibility facade for the backup durable job-store path."""
    return _persistence_job_store_backup_path()


def _job_runtime_dir() -> Path:
    """Compatibility facade for the private job-attempt directory."""
    return _persistence_job_runtime_dir()


def _load_store() -> dict[str, Any]:
    """Compatibility facade for durable job-store loading."""
    return job_persistence.load_store()


def _save_store(store: dict[str, Any]) -> None:
    """Compatibility facade for durable job-store persistence."""
    job_persistence.save_store(store)


def _managed_job_liveness(job: dict[str, Any]) -> str:
    """Return the authoritative cross-process liveness state for a managed row."""
    return managed_job_lease_state(
        str(job.get("job_id") or ""),
        job.get("managed_lease_version"),
    )


def _managed_job_has_local_task(job: dict[str, Any]) -> bool:
    """Return whether this process owns one still-running managed task."""
    if str(job.get("runtime_instance_id") or "") != PROCESS_INSTANCE_ID:
        return False
    task = _MANAGED_JOB_TASKS.get(str(job.get("job_id") or ""))
    return task is not None and not task.done()


def _acquire_managed_job_lease(job_id: str) -> ManagedJobLease:
    """Acquire and retain one job lease before publishing active metadata."""
    if job_id in _MANAGED_JOB_LEASES:
        raise RuntimeError(f"managed job lease is already held: {job_id}")
    lease = ManagedJobLease(job_id)
    lease.acquire()
    _MANAGED_JOB_LEASES[job_id] = lease
    return lease


def _release_managed_job_lease(job_id: str) -> None:
    """Release one process-local managed-job lease after terminal persistence."""
    lease = _MANAGED_JOB_LEASES.pop(job_id, None)
    if lease is not None:
        lease.release()


def _shell_safe_name(value: str) -> str:
    """Return a stable persistent-shell name derived from a job name."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "-", value.strip())[:48].strip(".-")
    return cleaned or "job"


def _active_shell_ids(shells: Any) -> set[str]:
    """Extract active persistent shell ids from the shell list output."""
    data = shells.model_dump() if hasattr(shells, "model_dump") else shells
    return {
        str(item.get("shell_id") or item.get("session_id"))
        for item in data.get("shells", data.get("sessions", []))
        if item.get("shell_id") or item.get("session_id")
    }


def _runner_argv(paths: dict[str, Path], cwd: Path) -> list[str]:
    """Build the internal durable runner invocation for one attempt."""
    arguments = [
        "job-runner",
        "--command-file",
        str(paths["command"]),
        "--log-file",
        str(paths["log"]),
        "--status-file",
        str(paths["status"]),
        "--cwd",
        str(cwd),
        "--shell",
        get_settings().shell_executable,
        "--max-log-bytes",
        str(max(1, get_settings().max_job_log_bytes)),
    ]
    if getattr(sys, "frozen", False):
        return [sys.executable, *arguments]
    return [sys.executable, "-m", "local_shell_mcp.main", *arguments]


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _runner_command(argv: list[str], shell: str) -> str:
    """Quote an internal runner invocation for the configured parent shell."""
    name = Path(shell).name.lower()
    if name in {"powershell.exe", "powershell", "pwsh.exe", "pwsh"}:
        return "& " + " ".join(_powershell_quote(value) for value in argv)
    if name in {"cmd.exe", "cmd"}:
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def _prepare_attempt(
    job_id: str, attempt: int, command: str, cwd: Path
) -> tuple[dict[str, Path], str]:
    """Validate and materialize one durable attempt before starting its shell."""
    check_command_policy(command)
    paths = _attempt_paths(job_id, attempt)
    write_private_text(paths["command"], command)
    paths["log"].unlink(missing_ok=True)
    paths["status"].unlink(missing_ok=True)
    argv = _runner_argv(paths, cwd)
    return paths, _runner_command(argv, get_settings().shell_executable)


def _read_status_path(raw_path: Any) -> dict[str, Any] | None:
    if not raw_path:
        return None
    try:
        payload = json.loads(Path(str(raw_path)).read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _read_status(job: dict[str, Any]) -> dict[str, Any] | None:
    return _read_status_path(job.get("status_path"))


def _apply_status_payload(
    job: dict[str, Any], status_payload: dict[str, Any], updated: float
) -> dict[str, Any]:
    """Apply runner completion metadata to one mutable job row."""
    exit_code = status_payload.get("exit_code")
    completed_at = float(status_payload.get("completed_at") or updated)
    job.update(
        {
            "status": "succeeded" if exit_code == 0 else "failed",
            "updated_at": completed_at,
            "completed_at": completed_at,
            "exit_code": exit_code,
            "error": status_payload.get("error"),
            "log_truncated": bool(status_payload.get("log_truncated", False)),
            "output_bytes": int(status_payload.get("output_bytes") or 0),
        }
    )
    job.pop("shell_absence_confirmed", None)
    _clear_job_operation(job)
    return job


def _clear_pending_retry(job: dict[str, Any]) -> None:
    for key in (
        "pending_attempt",
        "pending_shell_id",
        "pending_command_path",
        "pending_log_path",
        "pending_status_path",
    ):
        job.pop(key, None)


def _adopt_pending_retry(job: dict[str, Any]) -> None:
    attempt = job.get("pending_attempt")
    if attempt is not None:
        job["attempts"] = int(attempt)
    for pending_key, active_key in (
        ("pending_shell_id", "shell_id"),
        ("pending_command_path", "command_path"),
        ("pending_log_path", "log_path"),
        ("pending_status_path", "status_path"),
    ):
        value = job.get(pending_key)
        if value:
            job[active_key] = value


def _refresh_job_status(
    job: dict[str, Any],
    active_shells: set[str] | None,
    now: float | None = None,
) -> dict[str, Any]:
    """Apply durable completion and authoritative live-shell reconciliation."""
    status = str(job.get("status") or "unknown")
    kind = str(job.get("kind") or "shell")
    if status == "lost" and kind == "shell":
        updated = now or _utc()
        status_payload = _read_status(job)
        if status_payload is not None:
            return _apply_status_payload(job, status_payload, updated)
        if active_shells is None:
            return job
        shell_id = _job_shell_id(job)
        if shell_id and shell_id in active_shells:
            job.pop("shell_absence_confirmed", None)
            job.update(
                {
                    "status": "running",
                    "updated_at": updated,
                    "completed_at": None,
                    "exit_code": None,
                    "error": "recovered a lost job whose shell is still active",
                }
            )
        else:
            job["shell_absence_confirmed"] = True
        return job
    if status not in ACTIVE_STATUSES:
        return job

    updated = now or _utc()
    if str(job.get("kind") or "shell") == "managed":
        if any(
            _job_operation_is_active(job, operation)
            for operation in ("start", "stop", "retry")
        ):
            return job
        if _managed_job_has_local_task(job):
            return job
        liveness = _managed_job_liveness(job)
        if liveness != "dead":
            return job
        _clear_job_operation(job)
        job.update(
            {
                "status": "stopped" if status == "stopping" else "lost",
                "updated_at": updated,
                "completed_at": updated,
                "exit_code": None,
                "error": (
                    None
                    if status == "stopping"
                    else "managed job is no longer running; retry it to resume the operation"
                ),
            }
        )
        return job
    if status == "starting" and _job_operation_is_active(job, "start"):
        return job
    if status == "retrying" and _job_operation_is_active(job, "retry"):
        return job
    if status == "stopping" and _job_operation_is_active(job, "stop"):
        return job

    if status == "starting":
        status_payload = _read_status(job)
        shell_id = _job_shell_id(job)
        if status_payload is not None:
            return _apply_status_payload(job, status_payload, updated)
        if active_shells is None:
            return job
        _clear_job_operation(job)
        if shell_id and shell_id in active_shells:
            job.update(
                {
                    "status": "running",
                    "updated_at": updated,
                    "last_started_at": job.get("last_started_at") or updated,
                    "completed_at": None,
                    "exit_code": None,
                    "error": "recovered job start after an interrupted state commit",
                }
            )
            return job
        job.update(
            {
                "status": "failed",
                "updated_at": updated,
                "completed_at": updated,
                "exit_code": None,
                "error": "job start was interrupted before a recoverable shell was created",
            }
        )
        return job

    if status == "retrying":
        pending_shell = str(job.get("pending_shell_id") or "")
        status_payload = _read_status_path(job.get("pending_status_path"))
        if status_payload is not None:
            _adopt_pending_retry(job)
            _clear_pending_retry(job)
            return _apply_status_payload(job, status_payload, updated)
        if active_shells is None:
            return job
        if pending_shell and pending_shell in active_shells:
            _adopt_pending_retry(job)
            _clear_pending_retry(job)
            _clear_job_operation(job)
            job.update(
                {
                    "status": "running",
                    "updated_at": updated,
                    "last_started_at": updated,
                    "completed_at": None,
                    "exit_code": None,
                    "error": "recovered retry after an interrupted state commit",
                }
            )
            return job
        if job.get("pending_attempt") is not None:
            _adopt_pending_retry(job)
        _clear_pending_retry(job)
        _clear_job_operation(job)
        job.update(
            {
                "status": "failed",
                "updated_at": updated,
                "completed_at": updated,
                "exit_code": None,
                "error": "retry was interrupted before a recoverable shell was committed",
            }
        )
        return job

    status_payload = _read_status(job)
    shell_id = _job_shell_id(job)
    if status_payload is not None:
        return _apply_status_payload(job, status_payload, updated)
    if active_shells is None:
        return job

    if status == "stopping":
        _clear_job_operation(job)
        if shell_id in active_shells:
            job.update(
                {
                    "status": "running",
                    "updated_at": updated,
                    "error": "recovered an interrupted stop request; shell is still active",
                }
            )
        else:
            job.update(
                {
                    "status": "stopped",
                    "updated_at": updated,
                    "completed_at": updated,
                    "exit_code": None,
                    "error": None,
                }
            )
        return job

    if shell_id in active_shells:
        return job
    job.update(
        {
            "status": "lost",
            "updated_at": updated,
            "completed_at": updated,
            "exit_code": None,
            "error": "job shell exited without a durable completion record",
            "shell_absence_confirmed": True,
        }
    )
    return job


def _read_log_tail(path: str | None, lines: int) -> str:
    """Read a bounded UTF-8 tail from a durable job log."""
    if not path:
        return ""
    target = Path(path)
    if not target.is_file():
        return ""
    max_bytes = max(1, int(get_settings().max_job_log_bytes))
    try:
        size = target.stat().st_size
        with target.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
            data = handle.read(max_bytes)
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace")
    if lines > 0:
        selected = text.splitlines()[-max(1, lines) :]
        text = "\n".join(selected)
        if data.endswith((b"\n", b"\r")) and text:
            text += "\n"
    return text


def register_managed_job_handler(kind: str, handler: ManagedJobHandler) -> None:
    """Register one process-local managed-job handler idempotently."""
    normalized = kind.strip()
    if not normalized:
        raise ValueError("managed job kind must not be empty")
    existing = _MANAGED_JOB_HANDLERS.get(normalized)
    if existing is not None and existing is not handler:
        raise ValueError(
            f"managed job handler already registered: {normalized}"
        )
    _MANAGED_JOB_HANDLERS[normalized] = handler


def _managed_store_update(
    operation: str,
    session_id: str,
    job_id: str,
    payload: dict[str, Any],
) -> None:
    """Apply one update after bounded retries or durably defer it in order."""
    for attempt in range(1, MANAGED_JOB_STORE_RETRY_ATTEMPTS + 1):
        try:
            with _store_transaction() as store:
                try:
                    job = _find_session_job(store, session_id, job_id)
                except KeyError:
                    if operation == "append_log":
                        return
                    raise
                _apply_managed_update(job, operation, payload)
            return
        except TimeoutError:
            if attempt == MANAGED_JOB_STORE_RETRY_ATTEMPTS:
                break
            audit(
                "managed_job_store_update_retry",
                session=session_id,
                job_id=job_id,
                operation=operation,
                attempt=attempt,
            )
            time.sleep(JOB_STORE_LOCK_RETRY_INTERVAL_S)
    _write_managed_deferred_update(session_id, job_id, operation, payload)


def _append_managed_log(
    session_id: str, job_id: str, path: str, message: str
) -> None:
    """Append one bounded line and durably update or journal output metadata."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = message if message.endswith("\n") else message + "\n"
    encoded = payload.encode("utf-8", errors="replace")
    max_bytes = max(1, int(get_settings().max_job_log_bytes))
    with target.open("a+b") as handle:
        with contextlib.suppress(OSError):
            target.chmod(0o600)
        handle.write(encoded)
        handle.flush()
        truncated = _compact_log(handle, max_bytes)
    _managed_store_update(
        "append_log",
        session_id,
        job_id,
        {
            "bytes": len(encoded),
            "truncated": truncated,
            "updated_at": _utc(),
        },
    )


def _update_managed_progress(
    session_id: str, job_id: str, progress: dict[str, Any]
) -> None:
    """Persist or journal one bounded managed-job progress snapshot."""
    normalized = _managed_json_dict(progress, label="progress")
    _managed_store_update(
        "update_progress",
        session_id,
        job_id,
        {"progress": normalized, "updated_at": _utc()},
    )


class ManagedJobContext:
    """Durable logging and progress interface supplied to managed-job handlers."""

    def __init__(self, session_id: str, job_id: str, log_path: str) -> None:
        self.session_id = session_id
        self.job_id = job_id
        self.log_path = log_path

    async def log(self, message: str) -> None:
        """Append one message to the bounded durable job log."""
        await asyncio.to_thread(
            _append_managed_log,
            self.session_id,
            self.job_id,
            self.log_path,
            str(message),
        )

    async def update_progress(self, **progress: Any) -> None:
        """Replace the durable structured progress snapshot."""
        await asyncio.to_thread(
            _update_managed_progress,
            self.session_id,
            self.job_id,
            progress,
        )


def _finish_managed_job(
    session_id: str,
    job_id: str,
    *,
    status: str,
    exit_code: int | None,
    error: str | None,
    result: dict[str, Any] | None = None,
) -> None:
    """Commit one terminal managed-job state without overwriting a completed row."""
    normalized_result = (
        _managed_json_dict(result, label="result")
        if result is not None
        else None
    )
    _managed_store_update(
        "finish",
        session_id,
        job_id,
        {
            "status": status,
            "completed_at": _utc(),
            "exit_code": exit_code,
            "error": error,
            "has_result": normalized_result is not None,
            "result": normalized_result,
        },
    )


async def _run_managed_job(
    session_id: str,
    job_id: str,
    kind: str,
    payload: dict[str, Any],
    log_path: str,
) -> None:
    """Run one registered managed handler and durably record its terminal state."""
    context = ManagedJobContext(session_id, job_id, log_path)
    handler = _MANAGED_JOB_HANDLERS[kind]
    try:
        result = await handler(context, dict(payload))
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            await context.log("job cancelled")
        await asyncio.to_thread(
            _finish_managed_job,
            session_id,
            job_id,
            status="stopped",
            exit_code=None,
            error=None,
        )
        raise
    except Exception as exc:
        error = f"{public_error_type(exc)}: {exc}"
        with contextlib.suppress(Exception):
            await context.log(error)
        await asyncio.to_thread(
            _finish_managed_job,
            session_id,
            job_id,
            status="failed",
            exit_code=1,
            error=error,
        )
    else:
        try:
            await asyncio.to_thread(
                _finish_managed_job,
                session_id,
                job_id,
                status="succeeded",
                exit_code=0,
                error=None,
                result=result,
            )
        except Exception as exc:
            error = f"{public_error_type(exc)}: {exc}"
            with contextlib.suppress(Exception):
                await context.log(error)
            await asyncio.to_thread(
                _finish_managed_job,
                session_id,
                job_id,
                status="failed",
                exit_code=1,
                error=error,
            )
    finally:
        current = asyncio.current_task()
        if _MANAGED_JOB_TASKS.get(job_id) is current:
            _MANAGED_JOB_TASKS.pop(job_id, None)
        _release_managed_job_lease(job_id)


def _launch_managed_job(
    session_id: str,
    job_id: str,
    kind: str,
    payload: dict[str, Any],
    log_path: str,
) -> None:
    """Create and retain one process-local managed-job task."""
    acquired_here = False
    if job_id not in _MANAGED_JOB_LEASES:
        _acquire_managed_job_lease(job_id)
        acquired_here = True
    try:
        task = asyncio.create_task(
            _run_managed_job(session_id, job_id, kind, payload, log_path),
            name=f"managed-job-{job_id}",
        )
        _MANAGED_JOB_TASKS[job_id] = task
    except BaseException:
        if acquired_here:
            _release_managed_job_lease(job_id)
        raise


async def start_managed_job(
    session_id: str,
    kind: str,
    payload: dict[str, Any],
    *,
    name: str | None = None,
    command: str | None = None,
    cwd: str = ".",
) -> JobStartOutput:
    """Start one controller-managed task under session lifecycle admission."""
    async with session_lifecycle_lock(session_id):
        return await _start_managed_job_unlocked(
            session_id,
            kind,
            payload,
            name=name,
            command=command,
            cwd=cwd,
        )


async def _start_managed_job_unlocked(
    session_id: str,
    kind: str,
    payload: dict[str, Any],
    *,
    name: str | None = None,
    command: str | None = None,
    cwd: str = ".",
) -> JobStartOutput:
    """Start one controller-managed task owned by an explicit agent session."""
    get_tool_session_store().touch_session(session_id)
    normalized_kind = kind.strip()
    if normalized_kind not in _MANAGED_JOB_HANDLERS:
        raise ValueError(f"unknown managed job kind: {normalized_kind}")
    normalized_payload = _managed_json_dict(payload, label="payload")
    job_id = _new_job_id()
    attempt = 1
    paths = _attempt_paths(job_id, attempt)
    write_private_text(paths["log"], "")
    now = _utc()
    display_name = name or f"{normalized_kind}-{job_id}"
    job: dict[str, Any] = {
        "job_id": job_id,
        "kind": "managed",
        "managed_kind": normalized_kind,
        "managed_payload": normalized_payload,
        "runtime_instance_id": PROCESS_INSTANCE_ID,
        "managed_lease_version": MANAGED_JOB_LEASE_VERSION,
        "name": display_name,
        "status": "running",
        "command": command or normalized_kind,
        "cwd": cwd,
        "session_id": session_id,
        "shell_id": None,
        "backend": "managed",
        "command_path": None,
        "log_path": str(paths["log"]),
        "status_path": None,
        "created_at": now,
        "updated_at": now,
        "last_started_at": now,
        "completed_at": None,
        "exit_code": None,
        "error": None,
        "log_truncated": False,
        "output_bytes": 0,
        "attempts": attempt,
        "progress": None,
        "result": None,
    }
    try:
        _acquire_managed_job_lease(job_id)
        with _store_transaction() as store:
            store["jobs"].append(job)
        _launch_managed_job(
            session_id,
            job_id,
            normalized_kind,
            normalized_payload,
            str(paths["log"]),
        )
    except BaseException:
        _release_managed_job_lease(job_id)
        _remove_attempt_paths(paths)
        with contextlib.suppress(Exception), _store_transaction() as store:
            store["jobs"] = [
                row
                for row in store.get("jobs", [])
                if row.get("job_id") != job_id
            ]
        raise
    audit(
        "job_start",
        job_id=job_id,
        session=session_id,
        backend="managed",
        kind=normalized_kind,
    )
    return JobStartOutput(**_public_job(job).model_dump())


def reset_managed_jobs_for_tests(*, clear_handlers: bool = False) -> None:
    """Cancel process-local managed tasks and optionally clear test handlers."""
    for task in tuple(_MANAGED_JOB_TASKS.values()):
        task.cancel()
    _MANAGED_JOB_TASKS.clear()
    for job_id in tuple(_MANAGED_JOB_LEASES):
        with contextlib.suppress(Exception):
            _release_managed_job_lease(job_id)
    job_recovery.reset_deferred_sequence_for_tests()
    if clear_handlers:
        _MANAGED_JOB_HANDLERS.clear()


async def job_start_execute(
    session_id: str,
    command: str,
    cwd: str = ".",
    name: str | None = None,
) -> JobStartOutput:
    """Start one durable command under session lifecycle admission."""
    async with session_lifecycle_lock(session_id):
        return await _job_start_execute_unlocked(
            session_id, command, cwd=cwd, name=name
        )


async def _job_start_execute_unlocked(
    session_id: str,
    command: str,
    cwd: str = ".",
    name: str | None = None,
) -> JobStartOutput:
    """Start one durable tracked command owned by an explicit agent session."""
    session = get_tool_session_store().touch_session(session_id)
    resolved_cwd = resolve_session_path(session, cwd, must_exist=True)
    job_id = _new_job_id()
    display_name = name or job_id
    shell_name = _shell_safe_name(f"{display_name}-{job_id}")
    paths, runner_command = _prepare_attempt(job_id, 1, command, resolved_cwd)
    now = _utc()
    active_shells = await authoritative_persistent_shell_ids_execute()
    job: dict[str, Any] = {
        "job_id": job_id,
        "kind": "shell",
        "name": display_name,
        "status": "starting",
        "command": command,
        "cwd": str(resolved_cwd),
        "session_id": session_id,
        "shell_id": shell_name,
        "backend": None,
        "command_path": str(paths["command"]),
        "log_path": str(paths["log"]),
        "status_path": str(paths["status"]),
        "created_at": now,
        "updated_at": now,
        "last_started_at": None,
        "completed_at": None,
        "exit_code": None,
        "error": None,
        "log_truncated": False,
        "output_bytes": 0,
        "attempts": 1,
    }
    operation_id = _begin_job_operation(job, "start")
    try:
        with _store_transaction() as store:
            retained = []
            for row in store.get("jobs", []):
                if not isinstance(row, dict):
                    continue
                if str(row.get("session_id") or "") == session_id:
                    _refresh_job_status(row, active_shells, now)
                retained.append(row)
            store["jobs"] = retained
            _prune_store(store)
            store["jobs"].append(job)
    except BaseException:
        _discard_job_operation(operation_id)
        _remove_attempt_paths(paths)
        raise

    shell = None
    try:
        try:
            shell = await start_persistent_shell_execute(
                str(resolved_cwd),
                shell_name,
                runner_command,
                owner_session_id=session_id,
            )
        except Exception as exc:
            _remove_attempt_paths(paths)
            with _store_transaction() as store:
                current = _find_session_job(store, session_id, job_id)
                if current.get(
                    "status"
                ) == "starting" and _job_operation_matches(
                    current, operation_id
                ):
                    _clear_job_operation(current)
                    completed = _utc()
                    current.update(
                        {
                            "status": "failed",
                            "updated_at": completed,
                            "completed_at": completed,
                            "error": f"start failed: {public_error_type(exc)}: {exc}",
                        }
                    )
            raise

        shell_data = shell.model_dump()
        changed_while_starting = False
        try:
            with _store_transaction() as store:
                current = _find_session_job(store, session_id, job_id)
                if current.get(
                    "status"
                ) != "starting" or not _job_operation_matches(
                    current, operation_id
                ):
                    changed_while_starting = True
                else:
                    started_at = _utc()
                    _clear_job_operation(current)
                    current.update(
                        {
                            "status": "running",
                            "shell_id": shell_data["shell_id"],
                            "backend": shell_data.get("backend"),
                            "updated_at": started_at,
                            "last_started_at": started_at,
                            "error": None,
                        }
                    )
                public = _public_job(current)
        except Exception:
            with contextlib.suppress(Exception):
                await kill_persistent_shell_execute(shell_data["shell_id"])
            _remove_attempt_paths(paths)
            raise
        if changed_while_starting:
            with contextlib.suppress(Exception):
                await kill_persistent_shell_execute(shell_data["shell_id"])
            _remove_attempt_paths(paths)
            raise RuntimeError(f"job changed while starting: {job_id}")
        audit(
            "job_start",
            job_id=job_id,
            session=session_id,
            shell_id=shell_data["shell_id"],
            cwd=str(resolved_cwd),
            command=command,
        )
        return JobStartOutput(**public.model_dump())
    finally:
        _discard_job_operation(operation_id)


async def job_reconcile_shell_jobs_execute() -> bool:
    """Reconcile durable state and, when available, live shell membership."""
    with _store_transaction() as store:
        jobs = store.get("jobs", [])
        if not isinstance(jobs, list):
            return True
        owner_session_ids = sorted(
            {
                str(row.get("session_id") or "")
                for row in jobs
                if isinstance(row, dict)
                and str(row.get("kind") or "shell") != "managed"
                and row.get("session_id")
            }
        )

    inventory_authoritative = True
    for session_id in owner_session_ids:
        async with session_lifecycle_lock(session_id):
            active_shells = await authoritative_persistent_shell_ids_execute()
            if active_shells is None:
                inventory_authoritative = False
            now = _utc()
            with _store_transaction() as store:
                jobs = store.get("jobs", [])
                if not isinstance(jobs, list):
                    continue
                for row in jobs:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("kind") or "shell") == "managed":
                        continue
                    if str(row.get("session_id") or "") != session_id:
                        continue
                    _refresh_job_status(row, active_shells, now)

    active_shells = await authoritative_persistent_shell_ids_execute()
    if active_shells is None:
        inventory_authoritative = False
    now = _utc()
    with _store_transaction() as store:
        jobs = store.get("jobs", [])
        if isinstance(jobs, list):
            for row in jobs:
                if not isinstance(row, dict):
                    continue
                if str(row.get("kind") or "shell") == "managed":
                    continue
                if row.get("session_id"):
                    continue
                _refresh_job_status(row, active_shells, now)
        _prune_store(store)
    return inventory_authoritative


async def job_list_execute(
    session_id: str, include_finished: bool = True
) -> JobListOutput:
    """List one session's jobs under lifecycle-safe reconciliation."""
    async with session_lifecycle_lock(session_id):
        return await _job_list_execute_unlocked(
            session_id, include_finished=include_finished
        )


async def _job_list_execute_unlocked(
    session_id: str, include_finished: bool = True
) -> JobListOutput:
    """List and recover one session's jobs while its lifecycle lock is held."""
    get_tool_session_store().touch_session(session_id)
    active = await authoritative_persistent_shell_ids_execute()
    now = _utc()
    with _store_transaction() as store:
        jobs = store.get("jobs", [])
        if not isinstance(jobs, list):
            jobs = []
            store["jobs"] = jobs
        for row in jobs:
            if not isinstance(row, dict):
                continue
            if str(row.get("session_id") or "") != session_id:
                continue
            _refresh_job_status(row, active, now)
        _prune_store(store)
        owned = _session_jobs(store["jobs"], session_id)
        rows = [
            _public_job(row)
            for row in owned
            if include_finished or row.get("status") not in TERMINAL_STATUSES
        ]
        counts: dict[str, int] = {}
        for row in owned:
            status = str(row.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
    rows.sort(key=lambda item: item.created_at, reverse=True)
    return JobListOutput(jobs=rows, counts=counts)


async def job_tail_execute(
    session_id: str, job_id: str, lines: int = 200
) -> JobTailOutput:
    """Read one job under lifecycle-safe status reconciliation."""
    async with session_lifecycle_lock(session_id):
        return await _job_tail_execute_unlocked(session_id, job_id, lines)


async def _job_tail_execute_unlocked(
    session_id: str, job_id: str, lines: int = 200
) -> JobTailOutput:
    """Read one job while its owner lifecycle lock is held."""
    get_tool_session_store().touch_session(session_id)
    managed = job_id in managed_job_id_set(session_id, [job_id])
    active = (
        set() if managed else await authoritative_persistent_shell_ids_execute()
    )
    with _store_transaction() as store:
        job = _find_session_job(store, session_id, job_id)
        job = _refresh_job_status(job, active)
        public = _public_job(job)
        log_path = str(job.get("log_path") or "")
        shell_id = _job_shell_id(job)
        status = str(job.get("status") or "unknown")

    output = _read_log_tail(log_path, lines)
    if not output and status in ACTIVE_STATUSES and shell_id:
        try:
            tail = await read_persistent_shell_output_execute(shell_id, lines)
            output = str(tail.model_dump().get("output", ""))
        except Exception as exc:
            if active is not None:
                with _store_transaction() as store:
                    current = _find_session_job(store, session_id, job_id)
                    if (
                        current.get("status") == "running"
                        and _job_shell_id(current) == shell_id
                    ):
                        completed = _utc()
                        if shell_id in active:
                            current.update(
                                {
                                    "updated_at": completed,
                                    "error": (
                                        "persistent shell output capture failed: "
                                        f"{exc}"
                                    ),
                                }
                            )
                        else:
                            current.update(
                                {
                                    "status": "lost",
                                    "updated_at": completed,
                                    "completed_at": completed,
                                    "error": str(exc),
                                    "shell_absence_confirmed": True,
                                }
                            )
                    public = _public_job(current)

    message = None
    if public.status in TERMINAL_STATUSES:
        message = (
            f"job completed with exit code {public.exit_code}"
            if public.exit_code is not None
            else f"job is {public.status}"
        )
    return JobTailOutput(job=public, output=output, message=message)


async def _stop_managed_job(
    session_id: str,
    job_id: str,
    operation_id: str,
) -> JobStopOutput:
    """Cancel one active process-local managed task and retain its durable log."""
    task = _MANAGED_JOB_TASKS.get(job_id)
    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    with _store_transaction() as store:
        job = _find_session_job(store, session_id, job_id)
        if job.get("status") == "stopping" and _job_operation_matches(
            job, operation_id
        ):
            completed = _utc()
            job.update(
                {
                    "status": "stopped",
                    "updated_at": completed,
                    "completed_at": completed,
                    "exit_code": None,
                    "error": None,
                }
            )
            _clear_job_operation(job)
        public = _public_job(job)
    killed = public.status == "stopped"
    audit(
        "job_stop",
        job_id=job_id,
        session=session_id,
        backend="managed",
        killed=killed,
    )
    return JobStopOutput(job=public, killed=killed, stderr="")


async def _stop_managed_job_without_session_admission(
    session_id: str,
    job_id: str,
) -> JobStopOutput:
    """Stop one managed job when its owner session may already be terminating."""
    operation_id = ""
    try:
        with _store_transaction() as store:
            job = _refresh_job_status(
                _find_session_job(store, session_id, job_id), set()
            )
            if job.get("status") != "running":
                return JobStopOutput(
                    job=_public_job(job), killed=False, stderr=""
                )
            if str(job.get("kind") or "shell") != "managed":
                raise RuntimeError(f"job is not controller-managed: {job_id}")
            if not _managed_job_has_local_task(job):
                return JobStopOutput(
                    job=_public_job(job),
                    killed=False,
                    stderr=(
                        "managed job is owned by another live or uncertain runtime"
                    ),
                )
            job["status"] = "stopping"
            job["updated_at"] = _utc()
            operation_id = _begin_job_operation(job, "stop")
    except BaseException:
        _discard_job_operation(operation_id)
        raise
    try:
        return await _stop_managed_job(session_id, job_id, operation_id)
    finally:
        _discard_job_operation(operation_id)


async def job_stop_managed_references_execute(
    referenced_session_id: str,
    *,
    managed_kind: str,
    payload_key: str,
) -> list[str]:
    """Stop active managed jobs whose durable payload references one session."""
    candidates: list[tuple[str, str]] = []
    with _store_transaction() as store:
        for row in store.get("jobs", []):
            if not isinstance(row, dict):
                continue
            if str(row.get("kind") or "shell") != "managed":
                continue
            if str(row.get("managed_kind") or "") != managed_kind:
                continue
            payload = row.get("managed_payload")
            if not isinstance(payload, dict):
                continue
            if str(payload.get(payload_key) or "") != referenced_session_id:
                continue
            job = _refresh_job_status(row, set())
            if job.get("status") != "running":
                continue
            owner_session_id = str(job.get("session_id") or "")
            job_id = str(job.get("job_id") or "")
            if owner_session_id and job_id:
                candidates.append((owner_session_id, job_id))

    stopped: list[str] = []
    for owner_session_id, job_id in candidates:
        result = await _stop_managed_job_without_session_admission(
            owner_session_id, job_id
        )
        if result.killed or result.job.status in CONFIRMED_TERMINAL_STATUSES:
            stopped.append(job_id)
            continue
        raise RuntimeError(
            "managed job could not be confirmed stopped: "
            f"{job_id}: status={result.job.status!r}"
        )
    return stopped


async def job_stop_execute(session_id: str, job_id: str) -> JobStopOutput:
    """Stop one tracked command through a serialized lifecycle transition."""
    async with session_lifecycle_lock(session_id):
        return await _job_stop_execute_unlocked(session_id, job_id)


async def _job_stop_execute_unlocked(
    session_id: str, job_id: str
) -> JobStopOutput:
    """Stop one tracked command while its owner lifecycle lock is held."""
    get_tool_session_store().touch_session(session_id)
    managed = job_id in managed_job_id_set(session_id, [job_id])
    active = (
        set() if managed else await authoritative_persistent_shell_ids_execute()
    )
    operation_id = ""
    shell_id = ""
    try:
        with _store_transaction() as store:
            job = _find_session_job(store, session_id, job_id)
            job = _refresh_job_status(job, active)
            managed = str(job.get("kind") or "shell") == "managed"
            shell_id = _job_shell_id(job)
            if job.get("status") == "lost" and not managed:
                if active is None:
                    return JobStopOutput(
                        job=_public_job(job), killed=False, stderr=""
                    )
                if shell_id not in active:
                    completed = _utc()
                    job.update(
                        {
                            "status": "stopped",
                            "updated_at": completed,
                            "completed_at": completed,
                            "exit_code": None,
                            "error": None,
                        }
                    )
                    return JobStopOutput(
                        job=_public_job(job), killed=False, stderr=""
                    )
                job.update(
                    {
                        "status": "running",
                        "updated_at": _utc(),
                        "completed_at": None,
                    }
                )
            if job.get("status") != "running":
                return JobStopOutput(
                    job=_public_job(job), killed=False, stderr=""
                )
            if managed and not _managed_job_has_local_task(job):
                return JobStopOutput(
                    job=_public_job(job),
                    killed=False,
                    stderr=(
                        "managed job is owned by another live or uncertain runtime"
                    ),
                )
            job["status"] = "stopping"
            job["updated_at"] = _utc()
            operation_id = _begin_job_operation(job, "stop")
    except BaseException:
        _discard_job_operation(operation_id)
        raise

    try:
        if managed:
            return await _stop_managed_job(session_id, job_id, operation_id)
        try:
            result = await kill_persistent_shell_execute(shell_id)
        except Exception as exc:
            still_active = True
            active_after_failure = (
                await authoritative_persistent_shell_ids_execute()
            )
            if active_after_failure is not None:
                still_active = shell_id in active_after_failure
            with _store_transaction() as store:
                job = _find_session_job(store, session_id, job_id)
                if (
                    job.get("status") == "stopping"
                    and _job_shell_id(job) == shell_id
                    and _job_operation_matches(job, operation_id)
                ):
                    completed = _utc()
                    job["status"] = "running" if still_active else "stopped"
                    job["updated_at"] = completed
                    job["error"] = (
                        f"stop failed: {public_error_type(exc)}: {exc}"
                    )
                    if not still_active:
                        job["completed_at"] = completed
                    else:
                        job["completed_at"] = None
                    _clear_job_operation(job)
            raise

        data = result.model_dump()
        killed = bool(data.get("killed"))
        stderr = str(data.get("stderr") or "")
        active_after_stop: set[str] | None = None
        if not killed:
            active_after_stop = (
                await authoritative_persistent_shell_ids_execute()
            )
        with _store_transaction() as store:
            job = _find_session_job(store, session_id, job_id)
            if (
                job.get("status") == "stopping"
                and _job_shell_id(job) == shell_id
                and _job_operation_matches(job, operation_id)
            ):
                completed = _utc()
                if killed:
                    status = "stopped"
                elif active_after_stop is None or shell_id in active_after_stop:
                    status = "running"
                else:
                    status = "stopped"
                job.update(
                    {
                        "status": status,
                        "updated_at": completed,
                        "completed_at": completed
                        if status == "stopped"
                        else None,
                        "exit_code": None,
                        "error": None
                        if status == "stopped"
                        else stderr or "shell was not stopped",
                    }
                )
                _clear_job_operation(job)
            public = _public_job(job)
        audit(
            "job_stop",
            job_id=job_id,
            session=session_id,
            shell_id=shell_id,
            killed=killed,
        )
        return JobStopOutput(job=public, killed=killed, stderr=stderr)
    finally:
        _discard_job_operation(operation_id)


async def _retry_managed_job(session_id: str, job_id: str) -> JobRetryOutput:
    """Relaunch one terminal managed operation from its durable handler payload."""
    operation_id = ""
    paths: dict[str, Path] | None = None
    attempts = 0
    try:
        with _store_transaction() as store:
            job = _refresh_job_status(
                _find_session_job(store, session_id, job_id), set()
            )
            if job.get("status") in ACTIVE_STATUSES:
                raise RuntimeError(f"job is still active: {job_id}")
            kind = str(job.get("managed_kind") or "")
            if kind not in _MANAGED_JOB_HANDLERS:
                raise RuntimeError(
                    f"managed job handler is unavailable: {kind}"
                )
            payload = _managed_json_dict(
                job.get("managed_payload"), label="payload"
            )
            attempts = int(job.get("attempts") or 1) + 1
        _acquire_managed_job_lease(job_id)
        paths = _attempt_paths(job_id, attempts)
        write_private_text(paths["log"], "")
        with _store_transaction() as store:
            job = _refresh_job_status(
                _find_session_job(store, session_id, job_id), set()
            )
            if job.get("status") in ACTIVE_STATUSES:
                raise RuntimeError(f"job became active during retry: {job_id}")
            job.update(
                {
                    "status": "retrying",
                    "updated_at": _utc(),
                    "pending_attempt": attempts,
                    "pending_log_path": str(paths["log"]),
                    "progress": None,
                    "result": None,
                    "completed_at": None,
                    "exit_code": None,
                    "error": None,
                    "log_truncated": False,
                    "output_bytes": 0,
                    "runtime_instance_id": PROCESS_INSTANCE_ID,
                    "managed_lease_version": MANAGED_JOB_LEASE_VERSION,
                }
            )
            operation_id = _begin_job_operation(job, "retry")
        _launch_managed_job(
            session_id,
            job_id,
            kind,
            payload,
            str(paths["log"]),
        )
        with _store_transaction() as store:
            current = _find_session_job(store, session_id, job_id)
            if current.get("status") == "retrying" and _job_operation_matches(
                current, operation_id
            ):
                current.update(
                    {
                        "status": "running",
                        "attempts": attempts,
                        "log_path": str(paths["log"]),
                        "updated_at": _utc(),
                        "last_started_at": _utc(),
                    }
                )
                _clear_pending_retry(current)
                _clear_job_operation(current)
            public = _public_job(current)
        _remove_attempt_files(job_id, keep_attempt=attempts)
        audit(
            "job_retry",
            job_id=job_id,
            session=session_id,
            backend="managed",
            attempts=attempts,
        )
        return JobRetryOutput(**public.model_dump())
    except BaseException as exc:
        task = _MANAGED_JOB_TASKS.get(job_id)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        _release_managed_job_lease(job_id)
        _remove_attempt_paths(paths)
        if operation_id:
            with contextlib.suppress(Exception), _store_transaction() as store:
                current = _find_session_job(store, session_id, job_id)
                if _job_operation_matches(current, operation_id):
                    completed = _utc()
                    current.update(
                        {
                            "status": "failed",
                            "attempts": attempts
                            or int(current.get("attempts") or 1),
                            "updated_at": completed,
                            "completed_at": completed,
                            "exit_code": None,
                            "error": f"retry failed: {public_error_type(exc)}: {exc}",
                        }
                    )
                    _clear_pending_retry(current)
                    _clear_job_operation(current)
        raise
    finally:
        _discard_job_operation(operation_id)


def _job_lifecycle_session_ids(session_id: str, job_id: str) -> tuple[str, ...]:
    """Return all session ids whose lifecycle constrains one job retry."""
    session_ids = {session_id}
    with _store_transaction() as store:
        job = _find_session_job(store, session_id, job_id)
        if str(job.get("kind") or "shell") == "managed":
            payload = job.get("managed_payload")
            if isinstance(payload, dict):
                destination = str(payload.get("dst_session_id") or "")
                if destination:
                    session_ids.add(destination)
    return tuple(sorted(session_ids))


async def job_retry_execute(session_id: str, job_id: str) -> JobRetryOutput:
    """Retry one job under session lifecycle admission."""
    lifecycle_session_ids = _job_lifecycle_session_ids(session_id, job_id)
    async with session_lifecycle_locks(lifecycle_session_ids):
        store = get_tool_session_store()
        for lifecycle_session_id in lifecycle_session_ids:
            store.touch_session(lifecycle_session_id)
        return await _job_retry_execute_unlocked(session_id, job_id)


async def _job_retry_execute_unlocked(
    session_id: str, job_id: str
) -> JobRetryOutput:
    """Retry a terminal job with durable two-phase state transitions."""
    session = get_tool_session_store().touch_session(session_id)
    managed = job_id in managed_job_id_set(session_id, [job_id])
    if managed:
        return await _retry_managed_job(session_id, job_id)
    active = await authoritative_persistent_shell_ids_execute()
    operation_id = ""
    try:
        with _store_transaction() as store:
            job = _find_session_job(store, session_id, job_id)
            job = _refresh_job_status(job, active)
            if job.get("status") in ACTIVE_STATUSES:
                raise RuntimeError(f"job is still active: {job_id}")
            attempts = int(job.get("attempts") or 1) + 1
            command = str(job.get("command") or "")
            resolved_cwd = resolve_session_path(
                session, str(job.get("cwd") or "."), must_exist=True
            )
            display_name = str(job.get("name") or job_id)
            shell_name = _shell_safe_name(f"{display_name}-{job_id}-{attempts}")
            job.update(
                {
                    "status": "retrying",
                    "updated_at": _utc(),
                    "pending_attempt": attempts,
                    "pending_shell_id": shell_name,
                }
            )
            operation_id = _begin_job_operation(job, "retry")
    except BaseException:
        _discard_job_operation(operation_id)
        raise

    paths: dict[str, Path] | None = None
    try:
        try:
            paths, runner_command = _prepare_attempt(
                job_id, attempts, command, resolved_cwd
            )
            with _store_transaction() as store:
                current = _find_session_job(store, session_id, job_id)
                if current.get(
                    "status"
                ) != "retrying" or not _job_operation_matches(
                    current, operation_id
                ):
                    raise RuntimeError(
                        f"job changed while preparing retry: {job_id}"
                    )
                current.update(
                    {
                        "pending_command_path": str(paths["command"]),
                        "pending_log_path": str(paths["log"]),
                        "pending_status_path": str(paths["status"]),
                    }
                )
            shell = await start_persistent_shell_execute(
                str(resolved_cwd),
                shell_name,
                runner_command,
                owner_session_id=session_id,
            )
        except Exception as exc:
            _remove_attempt_paths(paths)
            with _store_transaction() as store:
                current = _find_session_job(store, session_id, job_id)
                if current.get(
                    "status"
                ) == "retrying" and _job_operation_matches(
                    current, operation_id
                ):
                    if current.get("pending_attempt") is not None:
                        current["attempts"] = int(current["pending_attempt"])
                    _clear_pending_retry(current)
                    _clear_job_operation(current)
                    completed = _utc()
                    current.update(
                        {
                            "status": "failed",
                            "updated_at": completed,
                            "completed_at": completed,
                            "exit_code": None,
                            "error": f"retry failed: {public_error_type(exc)}: {exc}",
                        }
                    )
            raise

        shell_data = shell.model_dump()
        changed_while_retrying = False
        try:
            with _store_transaction() as store:
                current = _find_session_job(store, session_id, job_id)
                if current.get(
                    "status"
                ) != "retrying" or not _job_operation_matches(
                    current, operation_id
                ):
                    changed_while_retrying = True
                else:
                    _adopt_pending_retry(current)
                    _clear_pending_retry(current)
                    _clear_job_operation(current)
                    started_at = _utc()
                    current.update(
                        {
                            "status": "running",
                            "cwd": str(resolved_cwd),
                            "shell_id": shell_data["shell_id"],
                            "backend": shell_data.get("backend"),
                            "updated_at": started_at,
                            "last_started_at": started_at,
                            "completed_at": None,
                            "exit_code": None,
                            "error": None,
                            "log_truncated": False,
                            "output_bytes": 0,
                        }
                    )
                public = _public_job(current)
        except Exception:
            with contextlib.suppress(Exception):
                await kill_persistent_shell_execute(shell_data["shell_id"])
            _remove_attempt_paths(paths)
            raise
        if changed_while_retrying:
            with contextlib.suppress(Exception):
                await kill_persistent_shell_execute(shell_data["shell_id"])
            _remove_attempt_paths(paths)
            raise RuntimeError(f"job changed while retrying: {job_id}")
        _remove_attempt_files(job_id, keep_attempt=attempts)
        audit(
            "job_retry",
            job_id=job_id,
            session=session_id,
            shell_id=shell_data["shell_id"],
            attempts=attempts,
        )
        return JobRetryOutput(**public.model_dump())
    finally:
        _discard_job_operation(operation_id)


async def managed_job_list_execute(
    session_id: str, include_finished: bool
) -> JobListOutput:
    """List only controller-managed jobs owned by one explicit session."""
    get_tool_session_store().touch_session(session_id)
    now = _utc()
    with _store_transaction() as store:
        for row in store.get("jobs", []):
            if (
                _job_agent_session_id(row) == session_id
                and str(row.get("kind") or "shell") == "managed"
            ):
                _refresh_job_status(row, set(), now)
        _prune_store(store)
        owned = [
            row
            for row in store.get("jobs", [])
            if _job_agent_session_id(row) == session_id
            and str(row.get("kind") or "shell") == "managed"
        ]
        rows = [
            _public_job(row)
            for row in owned
            if include_finished or row.get("status") not in TERMINAL_STATUSES
        ]
        counts: dict[str, int] = {}
        for row in owned:
            status = str(row.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
    rows.sort(key=lambda item: item.created_at, reverse=True)
    return JobListOutput(jobs=rows, counts=counts)


def managed_job_id_set(session_id: str, job_ids: list[str]) -> set[str]:
    """Return requested identifiers owned by controller-managed jobs."""
    requested = set(job_ids)
    if not requested:
        return set()
    with _store_transaction() as store:
        return {
            str(row.get("job_id") or "")
            for row in store.get("jobs", [])
            if _job_agent_session_id(row) == session_id
            and str(row.get("kind") or "shell") == "managed"
            and str(row.get("job_id") or "") in requested
        }


async def job_local_execute(
    session_id: str,
    list_jobs: bool = False,
    poll: list[str] | None = None,
    cancel: list[str] | None = None,
    retry: list[str] | None = None,
    include_finished: bool = True,
    lines: int = 200,
) -> JobOutput:
    """Run one tracked-job companion operation against the local job store."""
    selected = [poll is not None, cancel is not None, retry is not None]
    if list_jobs and any(selected):
        raise ValueError(
            "list_jobs cannot be combined with poll, cancel, or retry"
        )
    if sum(selected) > 1:
        raise ValueError("poll, cancel, and retry are mutually exclusive")

    if list_jobs or not any(selected):
        result = await job_list_execute(session_id, include_finished)
        return JobOutput(
            operation="list",
            jobs=result.jobs,
            counts=result.counts,
            message=(
                "No tracked jobs in this session."
                if not result.jobs
                else "Tracked job snapshot for this session."
            ),
        )

    if poll is not None:
        outputs = [
            await job_tail_execute(session_id, item, lines) for item in poll
        ]
        return JobOutput(operation="poll", outputs=outputs)

    if cancel is not None:
        cancelled = [
            await job_stop_execute(session_id, item) for item in cancel
        ]
        return JobOutput(operation="cancel", cancelled=cancelled)

    retried = [
        await job_retry_execute(session_id, item) for item in retry or []
    ]
    return JobOutput(operation="retry", retried=retried)
