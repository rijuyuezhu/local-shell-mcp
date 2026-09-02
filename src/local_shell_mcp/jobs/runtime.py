"""Shared durable tracked-job runtime, persistence, and runner helpers."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from ..ops.shell import (
    authoritative_persistent_shell_ids_execute,
    read_persistent_shell_output_execute,
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
)
from . import lifecycle as job_lifecycle
from . import managed as job_managed
from . import persistence as job_persistence
from . import recovery as job_recovery
from . import shell as job_shell
from . import state as job_state
from .persistence import (
    JOB_STORE_VERSION as _JOB_STORE_VERSION,
)
from .persistence import (
    TERMINAL_STATUSES,
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
from .runner import run_job_runner_from_args as _run_job_runner_from_args
from .state import (
    ACTIVE_STATUSES,
    JobStatusPayload,
    MutableJobRow,
)
from .state import (
    MANAGED_STATE_MAX_BYTES as _STATE_MANAGED_STATE_MAX_BYTES,
)
from .state import (
    find_session_job as _state_find_session_job,
)
from .state import (
    job_shell_id as _job_shell_id,
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
CONFIRMED_TERMINAL_STATUSES = job_state.CONFIRMED_TERMINAL_STATUSES
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
_store_transaction: Any = job_recovery.store_transaction
_shell_safe_name = job_lifecycle._shell_safe_name
_prepare_attempt = job_lifecycle._prepare_attempt
_clear_pending_retry = job_lifecycle._clear_pending_retry
_adopt_pending_retry = job_lifecycle._adopt_pending_retry
ManagedJobContext = job_managed.ManagedJobContext
ManagedJobHandler = job_managed.ManagedJobHandler
_managed_job_liveness = job_managed._managed_job_liveness
_managed_job_has_local_task = job_managed._managed_job_has_local_task
register_managed_job_handler = job_managed.register_managed_job_handler
start_managed_job = job_managed.start_managed_job
_start_managed_job_unlocked = job_managed._start_managed_job_unlocked
reset_managed_jobs_for_tests = job_managed.reset_managed_jobs_for_tests
_managed_store_update = job_managed._managed_store_update
_stop_managed_job = job_managed._stop_managed_job
_stop_managed_job_without_session_admission = (
    job_managed._stop_managed_job_without_session_admission
)
job_stop_managed_references_execute = (
    job_managed.job_stop_managed_references_execute
)
_retry_managed_job = job_managed._retry_managed_job
managed_job_list_execute = job_managed.managed_job_list_execute
managed_job_id_set = job_managed.managed_job_id_set
_job_start_execute_unlocked = job_shell.start_shell_job_unlocked
job_reconcile_shell_jobs_execute = job_shell.reconcile_shell_jobs_execute


def _runner_command(argv: list[str], shell: str) -> str:
    """Compatibility facade for quoting one durable runner command."""
    return job_lifecycle._runner_command(argv, shell)


def _attempt_paths(job_id: str, attempt: int) -> dict[str, Path]:
    """Compatibility facade retaining the historical mutable-dict test surface."""
    return cast(dict[str, Path], job_persistence.attempt_paths(job_id, attempt))


def _find_session_job(
    store: Mapping[str, Any], session_id: str, job_id: str
) -> dict[str, Any]:
    """Compatibility facade retaining the historical generic row mapping."""
    return cast(
        dict[str, Any], _state_find_session_job(store, session_id, job_id)
    )


def _read_status(job: Mapping[str, Any]) -> JobStatusPayload | None:
    """Compatibility facade for reading one durable attempt status."""
    return job_lifecycle._read_status(job)


def _read_status_path(raw_path: Any) -> JobStatusPayload | None:
    """Compatibility facade for reading one explicit durable status path."""
    return job_lifecycle._read_status_path(raw_path)


def _refresh_job_status(
    job: MutableJobRow,
    active_shells: set[str] | None,
    now: float | None = None,
) -> dict[str, Any]:
    """Compatibility facade for durable shell/managed status reconciliation."""
    return cast(
        dict[str, Any],
        job_lifecycle._refresh_job_status(
            job,
            active_shells,
            now,
            managed_job_has_local_task=_managed_job_has_local_task,
            managed_job_liveness=_managed_job_liveness,
            read_status=_read_status,
            read_status_path=_read_status_path,
        ),
    )


def _read_log_tail(path: str | None, lines: int) -> str:
    """Compatibility facade for bounded durable log reads."""
    return job_lifecycle._read_log_tail(path, lines)


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
    return cast(dict[str, Any], job_persistence.load_store())


def _save_store(store: dict[str, Any]) -> None:
    """Compatibility facade for durable job-store persistence."""
    job_persistence.save_store(store)


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


async def job_stop_execute(session_id: str, job_id: str) -> JobStopOutput:
    """Stop one tracked command through a serialized lifecycle transition."""
    async with session_lifecycle_lock(session_id):
        return await _job_stop_execute_unlocked(session_id, job_id)


async def _job_stop_execute_unlocked(
    session_id: str, job_id: str
) -> JobStopOutput:
    """Dispatch one lifecycle-safe stop to its authoritative backend."""
    get_tool_session_store().touch_session(session_id)
    if job_id in managed_job_id_set(session_id, [job_id]):
        return await _stop_managed_job_without_session_admission(
            session_id, job_id
        )
    return await job_shell.stop_shell_job_unlocked(session_id, job_id)


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
    """Dispatch one lifecycle-safe retry to its authoritative backend."""
    get_tool_session_store().touch_session(session_id)
    if job_id in managed_job_id_set(session_id, [job_id]):
        return await _retry_managed_job(session_id, job_id)
    return await job_shell.retry_shell_job_unlocked(session_id, job_id)


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
