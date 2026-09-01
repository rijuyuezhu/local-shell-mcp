"""Shared durable tracked-job runtime, persistence, and runner helpers."""

import contextlib
from pathlib import Path
from typing import Any

from ..audit import audit
from ..errors import public_error_type
from ..ops.shell import (
    authoritative_persistent_shell_ids_execute,
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
from . import lifecycle as job_lifecycle
from . import managed as job_managed
from . import persistence as job_persistence
from . import recovery as job_recovery
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
from .persistence import (
    remove_attempt_files as _remove_attempt_files,
)
from .persistence import (
    remove_attempt_paths as _remove_attempt_paths,
)
from .runner import run_job_runner_from_args as _run_job_runner_from_args
from .state import (
    ACTIVE_STATUSES,
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
    job_operation_matches as _job_operation_matches,
)
from .state import (
    job_shell_id as _job_shell_id,
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
CONFIRMED_TERMINAL_STATUSES = job_state.CONFIRMED_TERMINAL_STATUSES
_MANAGED_STATE_MAX_BYTES = _STATE_MANAGED_STATE_MAX_BYTES
_attempt_paths = job_persistence.attempt_paths
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


def _runner_command(argv: list[str], shell: str) -> str:
    """Compatibility facade for quoting one durable runner command."""
    return job_lifecycle._runner_command(argv, shell)


def _read_status(job: dict[str, Any]) -> dict[str, Any] | None:
    """Compatibility facade for reading one durable attempt status."""
    return job_lifecycle._read_status(job)


def _read_status_path(raw_path: Any) -> dict[str, Any] | None:
    """Compatibility facade for reading one explicit durable status path."""
    return job_lifecycle._read_status_path(raw_path)


def _refresh_job_status(
    job: dict[str, Any],
    active_shells: set[str] | None,
    now: float | None = None,
) -> dict[str, Any]:
    """Compatibility facade for durable shell/managed status reconciliation."""
    return job_lifecycle._refresh_job_status(
        job,
        active_shells,
        now,
        managed_job_has_local_task=_managed_job_has_local_task,
        managed_job_liveness=_managed_job_liveness,
        read_status=_read_status,
        read_status_path=_read_status_path,
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
    return job_persistence.load_store()


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
