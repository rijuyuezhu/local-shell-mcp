"""Shared durable tracked-job runtime, persistence, and runner helpers."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Generator
from pathlib import Path
from typing import Any, BinaryIO

from ..audit import audit
from ..config.settings import get_settings
from ..errors import public_error_type
from ..ops.shell import (
    _subprocess_env,
    check_command_policy,
    kill_persistent_shell_execute,
    list_persistent_shells_execute,
    read_persistent_shell_output_execute,
    start_persistent_shell_execute,
)
from ..schemas.result_models.jobs import (
    JobInfo,
    JobListOutput,
    JobOutput,
    JobRetryOutput,
    JobStartOutput,
    JobStopOutput,
    JobTailOutput,
)
from ..tool_session.store import (
    get_tool_session_store,
    resolve_session_path,
)
from ..utils.private_files import (
    atomic_write_private_text,
    private_file_lock,
    write_private_text,
)
from ..utils.serialization import to_jsonable

JOB_STORE_FILE_NAME = "jobs.json"
JOB_STORE_BACKUP_FILE_NAME = "jobs.json.bak"
JOB_STORE_LOCK_FILE_NAME = "jobs.lock"
JOB_STORE_VERSION = 2
JOB_STORE_LEGACY_VERSIONS = {1}
JOB_STORE_LOCK_TIMEOUT_S = 2.0
JOB_STORE_LOCK_RETRY_INTERVAL_S = 0.05
MANAGED_JOB_STORE_RETRY_ATTEMPTS = 2
MANAGED_DEFERRED_UPDATE_VERSION = 1
MANAGED_DEFERRED_APPLIED_KEY = "managed_deferred_update_ids"
MANAGED_DEFERRED_MAX_RECORD_BYTES = 524_288
TERMINAL_STATUSES = {"succeeded", "failed", "exited", "stopped", "lost"}
ACTIVE_STATUSES = {"starting", "running", "stopping", "retrying"}
_JOB_STORE_THREAD_LOCK = threading.RLock()
_MANAGED_DEFERRED_SEQUENCE_LOCK = threading.Lock()
_MANAGED_DEFERRED_NEXT_SEQUENCE: int | None = None
_ACTIVE_JOB_OPERATIONS: set[str] = set()
ManagedJobHandler = Callable[
    ["ManagedJobContext", dict[str, Any]], Awaitable[dict[str, Any] | None]
]
_MANAGED_JOB_HANDLERS: dict[str, ManagedJobHandler] = {}
_MANAGED_JOB_TASKS: dict[str, asyncio.Task[None]] = {}


def _utc() -> float:
    """Return the current Unix timestamp."""
    return time.time()


def _job_store_path() -> Path:
    """Return the primary tracked-job metadata path."""
    return get_settings().state_dir / JOB_STORE_FILE_NAME


def _job_store_backup_path() -> Path:
    """Return the fallback tracked-job metadata path."""
    return get_settings().state_dir / JOB_STORE_BACKUP_FILE_NAME


def _job_store_lock_path() -> Path:
    """Return the cross-process tracked-job lock path."""
    return get_settings().state_dir / JOB_STORE_LOCK_FILE_NAME


def _job_runtime_dir() -> Path:
    """Return the private directory containing job attempt logs and status files."""
    path = get_settings().state_dir / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.chmod(0o700)
    return path


def _managed_deferred_update_dir(*, create: bool = True) -> Path:
    """Return the private journal directory, creating it only for a writer."""
    path = get_settings().state_dir / "jobs" / "deferred"
    if create:
        path.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            path.chmod(0o700)
    return path


def _empty_store() -> dict[str, Any]:
    return {"version": JOB_STORE_VERSION, "jobs": []}


def _load_store_file(path: Path) -> dict[str, Any]:
    """Load and migrate one supported tracked-job store file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"unsupported or invalid job store: {path}")
    version = data.get("version")
    if (
        version != JOB_STORE_VERSION
        and version not in JOB_STORE_LEGACY_VERSIONS
    ):
        raise ValueError(f"unsupported or invalid job store: {path}")
    rows = data.get("jobs")
    if not isinstance(rows, list):
        raise ValueError(f"job store jobs field is invalid: {path}")
    jobs = [row for row in rows if isinstance(row, dict)]
    if version != JOB_STORE_VERSION:
        audit(
            "job_store_migrated",
            path=str(path),
            from_version=version,
            to_version=JOB_STORE_VERSION,
            jobs=len(jobs),
        )
    return {"version": JOB_STORE_VERSION, "jobs": jobs}


def _load_store() -> dict[str, Any]:
    """Load the primary store or recover from its backup without silent reset."""
    path = _job_store_path()
    backup_path = _job_store_backup_path()
    if not path.exists() and not backup_path.exists():
        return _empty_store()

    main_error: Exception | None = None
    if path.exists():
        try:
            return _load_store_file(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            main_error = exc
            audit("job_store_unreadable", path=str(path), error=repr(exc))

    if backup_path.exists():
        try:
            store = _load_store_file(backup_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            audit(
                "job_store_backup_unreadable",
                path=str(backup_path),
                error=repr(exc),
            )
        else:
            audit(
                "job_store_recovered",
                path=str(path),
                backup_path=str(backup_path),
            )
            return store

    raise RuntimeError(
        "Job store is unreadable and no valid backup is available; refusing to reset it"
    ) from main_error


def _attempt_paths(job_id: str, attempt: int) -> dict[str, Path]:
    """Return private command, log, and status paths for one job attempt."""
    stem = f"{job_id}-attempt-{attempt}"
    root = _job_runtime_dir()
    return {
        "command": root / f"{stem}.command",
        "log": root / f"{stem}.log",
        "status": root / f"{stem}.status.json",
    }


def _remove_attempt_paths(paths: dict[str, Path] | None) -> None:
    if not paths:
        return
    for path in paths.values():
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


def _remove_attempt_files(job_id: str, keep_attempt: int | None = None) -> None:
    """Remove runtime artifacts for pruned or superseded attempts."""
    if not job_id:
        return
    keep_stem = (
        f"{job_id}-attempt-{keep_attempt}."
        if keep_attempt is not None
        else None
    )
    for path in _job_runtime_dir().glob(f"{job_id}-attempt-*"):
        if keep_stem is not None and path.name.startswith(keep_stem):
            continue
        with contextlib.suppress(OSError):
            path.unlink()


def _prune_store(store: dict[str, Any]) -> None:
    """Bound retained terminal jobs while never deleting active operations."""
    jobs = [row for row in store.get("jobs", []) if isinstance(row, dict)]
    max_jobs = max(0, int(get_settings().max_jobs))
    active = [row for row in jobs if row.get("status") not in TERMINAL_STATUSES]
    finished = sorted(
        (row for row in jobs if row.get("status") in TERMINAL_STATUSES),
        key=lambda row: float(
            row.get("updated_at") or row.get("created_at") or 0
        ),
        reverse=True,
    )
    keep_finished = finished[: max(0, max_jobs - len(active))]
    keep_objects = {id(row) for row in [*active, *keep_finished]}
    removed = [row for row in jobs if id(row) not in keep_objects]
    store["jobs"] = [row for row in jobs if id(row) in keep_objects]
    for row in removed:
        _remove_attempt_files(str(row.get("job_id") or ""))


def _save_store(store: dict[str, Any]) -> None:
    """Atomically persist primary and backup stores after retention pruning."""
    _prune_store(store)
    store["version"] = JOB_STORE_VERSION
    path = _job_store_path()
    backup_path = _job_store_backup_path()
    payload = json.dumps(store, indent=2, sort_keys=True)
    atomic_write_private_text(path, payload)
    atomic_write_private_text(backup_path, payload)


def _next_managed_deferred_sequence() -> int:
    """Allocate a process-safe sequence continuing any journal left by restart."""
    global _MANAGED_DEFERRED_NEXT_SEQUENCE
    with _MANAGED_DEFERRED_SEQUENCE_LOCK:
        if _MANAGED_DEFERRED_NEXT_SEQUENCE is None:
            maximum = -1
            directory = _managed_deferred_update_dir(create=False)
            if directory.is_dir():
                for path in directory.glob("*.json"):
                    prefix = path.stem.split("-", 1)[0]
                    if prefix.isdigit():
                        maximum = max(maximum, int(prefix))
            _MANAGED_DEFERRED_NEXT_SEQUENCE = maximum + 1
        sequence = _MANAGED_DEFERRED_NEXT_SEQUENCE
        _MANAGED_DEFERRED_NEXT_SEQUENCE += 1
        return sequence


def _write_managed_deferred_update(
    session_id: str,
    job_id: str,
    operation: str,
    payload: dict[str, Any],
) -> Path:
    """Atomically journal one managed update after bounded lock contention."""
    update_id = (
        f"{_next_managed_deferred_sequence():020d}-"
        f"{time.time_ns():020d}-{uuid.uuid4().hex}"
    )
    path = _managed_deferred_update_dir() / f"{update_id}.json"
    record = {
        "version": MANAGED_DEFERRED_UPDATE_VERSION,
        "update_id": update_id,
        "session_id": session_id,
        "job_id": job_id,
        "operation": operation,
        "payload": payload,
    }
    encoded = json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(encoded.encode("utf-8")) > MANAGED_DEFERRED_MAX_RECORD_BYTES:
        raise ValueError(
            "managed deferred update exceeds the private journal limit"
        )
    atomic_write_private_text(path, encoded)
    audit(
        "managed_job_store_update_deferred",
        session=session_id,
        job_id=job_id,
        operation=operation,
        update_id=update_id,
        path=str(path),
    )
    return path


def _read_managed_deferred_record(path: Path) -> dict[str, Any]:
    """Read one bounded regular journal file without following POSIX symlinks."""
    if path.is_symlink() or (
        hasattr(path, "is_junction") and path.is_junction()
    ):
        raise ValueError("deferred update must not be a link")
    flags = os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
    flags |= int(getattr(os, "O_NOFOLLOW", 0))
    descriptor = os.open(path, flags)
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError("deferred update is not a regular file")
        if int(file_stat.st_size) > MANAGED_DEFERRED_MAX_RECORD_BYTES:
            raise ValueError(
                "deferred update exceeds the private journal limit"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(MANAGED_DEFERRED_MAX_RECORD_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(raw) > MANAGED_DEFERRED_MAX_RECORD_BYTES:
        raise ValueError("deferred update exceeds the private journal limit")
    record = json.loads(raw.decode("utf-8"))
    if not isinstance(record, dict):
        raise ValueError("deferred update is not an object")
    if record.get("version") != MANAGED_DEFERRED_UPDATE_VERSION:
        raise ValueError("unsupported deferred update version")
    update_id = str(record.get("update_id") or "")
    if not update_id:
        raise ValueError("deferred update id is missing")
    if update_id != path.stem:
        raise ValueError("deferred update id does not match its filename")
    if not str(record.get("session_id") or ""):
        raise ValueError("deferred update session id is missing")
    if not str(record.get("job_id") or ""):
        raise ValueError("deferred update job id is missing")
    if record.get("operation") not in {
        "append_log",
        "update_progress",
        "finish",
    }:
        raise ValueError("unsupported deferred update operation")
    if not isinstance(record.get("payload"), dict):
        raise ValueError("deferred update payload is not an object")
    return record


def _read_managed_deferred_updates() -> list[
    tuple[Path, dict[str, Any] | None, bool]
]:
    """Return ordered journal rows and whether each invalid row may be removed."""
    rows: list[tuple[Path, dict[str, Any] | None, bool]] = []
    directory = _managed_deferred_update_dir(create=False)
    if not directory.is_dir():
        return rows
    for path in sorted(directory.glob("*.json")):
        try:
            record = _read_managed_deferred_record(path)
        except OSError as exc:
            audit(
                "managed_job_deferred_update_unreadable",
                path=str(path),
                error=repr(exc),
            )
            rows.append((path, None, False))
        except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
            audit(
                "managed_job_deferred_update_invalid",
                path=str(path),
                error=repr(exc),
            )
            rows.append((path, None, True))
        else:
            rows.append((path, record, True))
    return rows


def _apply_managed_update(
    job: dict[str, Any], operation: str, payload: dict[str, Any]
) -> None:
    """Apply one already validated managed-state update to a mutable job row."""
    if operation == "append_log":
        job["output_bytes"] = int(job.get("output_bytes") or 0) + max(
            0, int(payload.get("bytes") or 0)
        )
        job["log_truncated"] = bool(job.get("log_truncated")) or bool(
            payload.get("truncated")
        )
        job["updated_at"] = float(payload.get("updated_at") or _utc())
        return
    if operation == "update_progress":
        if str(job.get("status") or "") in ACTIVE_STATUSES:
            job["progress"] = _managed_json_dict(
                payload.get("progress"), label="progress"
            )
            job["updated_at"] = float(payload.get("updated_at") or _utc())
        return
    if operation == "finish":
        if str(job.get("status") or "") not in ACTIVE_STATUSES:
            return
        completed = float(payload.get("completed_at") or _utc())
        job.update(
            {
                "status": str(payload.get("status") or "failed"),
                "updated_at": completed,
                "completed_at": completed,
                "exit_code": payload.get("exit_code"),
                "error": payload.get("error"),
            }
        )
        if bool(payload.get("has_result")):
            job["result"] = _managed_json_dict(
                payload.get("result"), label="result"
            )
        _clear_job_operation(job)
        return
    raise ValueError(f"unsupported managed update operation: {operation}")


def _reconcile_managed_deferred_updates(store: dict[str, Any]) -> list[Path]:
    """Replay each journal row once and return rows removable after store commit."""
    rows = _read_managed_deferred_updates()
    active_ids = {path.stem for path, _record, _removable in rows}
    for job in store.get("jobs", []):
        if not isinstance(job, dict):
            continue
        applied = [
            str(update_id)
            for update_id in job.get(MANAGED_DEFERRED_APPLIED_KEY, [])
            if str(update_id) in active_ids
        ]
        if applied:
            job[MANAGED_DEFERRED_APPLIED_KEY] = applied
        else:
            job.pop(MANAGED_DEFERRED_APPLIED_KEY, None)

    removable: list[Path] = []
    for path, record, should_remove in rows:
        if should_remove:
            removable.append(path)
        if record is None:
            continue
        session_id = str(record["session_id"])
        job_id = str(record["job_id"])
        try:
            job = _find_session_job(store, session_id, job_id)
        except KeyError:
            continue
        update_id = str(record["update_id"])
        applied = [
            str(item) for item in job.get(MANAGED_DEFERRED_APPLIED_KEY, [])
        ]
        if update_id in applied:
            continue
        try:
            _apply_managed_update(
                job,
                str(record["operation"]),
                dict(record["payload"]),
            )
        except (TypeError, ValueError) as exc:
            audit(
                "managed_job_deferred_update_invalid",
                path=str(path),
                session=session_id,
                job_id=job_id,
                error=repr(exc),
            )
            continue
        applied.append(update_id)
        job[MANAGED_DEFERRED_APPLIED_KEY] = applied
    return removable


def _remove_managed_deferred_updates(paths: list[Path]) -> None:
    """Remove journal rows only after their applied ids are durably saved."""
    for path in paths:
        with contextlib.suppress(OSError):
            path.unlink()


def _job_store_busy_error(*, lock_kind: str) -> TimeoutError:
    """Return one actionable public error while auditing the private lock path."""
    audit(
        "job_store_lock_timeout",
        path=str(_job_store_lock_path()),
        timeout_s=JOB_STORE_LOCK_TIMEOUT_S,
        lock_kind=lock_kind,
    )
    return TimeoutError(
        "job store is busy; another local-shell-mcp operation or process may be "
        "using the same state directory"
    )


@contextlib.contextmanager
def _store_transaction() -> Generator[dict[str, Any]]:
    """Serialize one bounded job-store transaction and reconcile deferred updates."""
    started = time.monotonic()
    if not _JOB_STORE_THREAD_LOCK.acquire(timeout=JOB_STORE_LOCK_TIMEOUT_S):
        raise _job_store_busy_error(lock_kind="thread")
    try:
        remaining = max(
            0.0,
            JOB_STORE_LOCK_TIMEOUT_S - (time.monotonic() - started),
        )
        lock_stack = contextlib.ExitStack()
        try:
            lock_stack.enter_context(
                private_file_lock(
                    _job_store_lock_path(),
                    timeout_s=remaining,
                    retry_interval_s=JOB_STORE_LOCK_RETRY_INTERVAL_S,
                )
            )
        except TimeoutError as exc:
            raise _job_store_busy_error(lock_kind="file") from exc
        with lock_stack:
            store = _load_store()
            deferred_paths = _reconcile_managed_deferred_updates(store)
            yield store
            _save_store(store)
            _remove_managed_deferred_updates(deferred_paths)
    finally:
        _JOB_STORE_THREAD_LOCK.release()


def _new_job_id() -> str:
    return "job_" + uuid.uuid4().hex[:12]


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


def _job_shell_id(job: dict[str, Any]) -> str:
    value = job.get("shell_id")
    return str(value) if value else ""


def _job_agent_session_id(job: dict[str, Any]) -> str | None:
    value = job.get("session_id")
    return value if isinstance(value, str) else None


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


def _begin_job_operation(job: dict[str, Any], kind: str) -> str:
    operation_id = f"{kind}_{uuid.uuid4().hex}"
    _ACTIVE_JOB_OPERATIONS.add(operation_id)
    job["operation_id"] = operation_id
    job["operation_kind"] = kind
    job["operation_started_at"] = _utc()
    return operation_id


def _job_operation_matches(job: dict[str, Any], operation_id: str) -> bool:
    return str(job.get("operation_id") or "") == operation_id


def _job_operation_is_active(job: dict[str, Any], kind: str) -> bool:
    operation_id = str(job.get("operation_id") or "")
    return (
        bool(operation_id)
        and str(job.get("operation_kind") or "") == kind
        and operation_id in _ACTIVE_JOB_OPERATIONS
    )


def _clear_job_operation(job: dict[str, Any]) -> None:
    for key in ("operation_id", "operation_kind", "operation_started_at"):
        job.pop(key, None)


def _refresh_job_status(
    job: dict[str, Any], active_shells: set[str], now: float | None = None
) -> dict[str, Any]:
    """Recover interrupted transitions and apply durable runner completion state."""
    status = str(job.get("status") or "unknown")
    if status not in ACTIVE_STATUSES:
        return job

    updated = now or _utc()
    if str(job.get("kind") or "shell") == "managed":
        if any(
            _job_operation_is_active(job, operation)
            for operation in ("start", "stop", "retry")
        ):
            return job
        task = _MANAGED_JOB_TASKS.get(str(job.get("job_id") or ""))
        if task is not None and not task.done():
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
        _clear_job_operation(job)
        if status_payload is not None:
            return _apply_status_payload(job, status_payload, updated)
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
        }
    )
    return job


def _public_job(job: dict[str, Any]) -> JobInfo:
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
            "error": (
                str(job["error"]) if job.get("error") is not None else None
            ),
            "log_truncated": bool(job.get("log_truncated", False)),
            "output_bytes": int(job.get("output_bytes") or 0),
            "attempts": int(job.get("attempts") or 1),
        }
    )


def _session_jobs(
    jobs: list[dict[str, Any]], session_id: str
) -> list[dict[str, Any]]:
    return [row for row in jobs if _job_agent_session_id(row) == session_id]


def _find_session_job(
    store: dict[str, Any], session_id: str, job_id: str
) -> dict[str, Any]:
    for row in store.get("jobs", []):
        if (
            row.get("job_id") == job_id
            and _job_agent_session_id(row) == session_id
        ):
            return row
    raise KeyError(f"job not found in session: {job_id}")


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


_MANAGED_STATE_MAX_BYTES = 262_144


def _managed_json_dict(value: Any, *, label: str) -> dict[str, Any]:
    """Normalize and bound one managed-job payload, progress, or result object."""
    normalized = to_jsonable(value)
    if not isinstance(normalized, dict):
        raise TypeError(f"managed job {label} must be a JSON object")
    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > _MANAGED_STATE_MAX_BYTES:
        raise ValueError(
            f"managed job {label} exceeds {_MANAGED_STATE_MAX_BYTES} bytes"
        )
    return normalized


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


def _launch_managed_job(
    session_id: str,
    job_id: str,
    kind: str,
    payload: dict[str, Any],
    log_path: str,
) -> None:
    """Create and retain one process-local managed-job task."""
    task = asyncio.create_task(
        _run_managed_job(session_id, job_id, kind, payload, log_path),
        name=f"managed-job-{job_id}",
    )
    _MANAGED_JOB_TASKS[job_id] = task


async def start_managed_job(
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
    global _MANAGED_DEFERRED_NEXT_SEQUENCE
    for task in tuple(_MANAGED_JOB_TASKS.values()):
        task.cancel()
    _MANAGED_JOB_TASKS.clear()
    _MANAGED_DEFERRED_NEXT_SEQUENCE = None
    if clear_handlers:
        _MANAGED_JOB_HANDLERS.clear()


async def job_start_execute(
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
            store["jobs"].append(job)
    except BaseException:
        _ACTIVE_JOB_OPERATIONS.discard(operation_id)
        _remove_attempt_paths(paths)
        raise

    shell = None
    try:
        try:
            shell = await start_persistent_shell_execute(
                str(resolved_cwd), shell_name, runner_command
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
        _ACTIVE_JOB_OPERATIONS.discard(operation_id)


async def job_list_execute(
    session_id: str, include_finished: bool = True
) -> JobListOutput:
    """List and recover tracked jobs owned by one agent session."""
    get_tool_session_store().touch_session(session_id)
    active = _active_shell_ids(await list_persistent_shells_execute())
    now = _utc()
    with _store_transaction() as store:
        jobs = [
            _refresh_job_status(row, active, now)
            for row in store.get("jobs", [])
        ]
        store["jobs"] = jobs
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
    """Read durable recent output and refresh one tracked job."""
    get_tool_session_store().touch_session(session_id)
    managed = job_id in managed_job_id_set(session_id, [job_id])
    active = (
        set()
        if managed
        else _active_shell_ids(await list_persistent_shells_execute())
    )
    with _store_transaction() as store:
        job = _refresh_job_status(
            _find_session_job(store, session_id, job_id), active
        )
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
            with _store_transaction() as store:
                current = _find_session_job(store, session_id, job_id)
                if (
                    current.get("status") == "running"
                    and _job_shell_id(current) == shell_id
                ):
                    completed = _utc()
                    current.update(
                        {
                            "status": "lost",
                            "updated_at": completed,
                            "completed_at": completed,
                            "error": str(exc),
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


async def job_stop_execute(session_id: str, job_id: str) -> JobStopOutput:
    """Stop one tracked command through a serialized lifecycle transition."""
    get_tool_session_store().touch_session(session_id)
    managed = job_id in managed_job_id_set(session_id, [job_id])
    active = (
        set()
        if managed
        else _active_shell_ids(await list_persistent_shells_execute())
    )
    operation_id = ""
    shell_id = ""
    try:
        with _store_transaction() as store:
            job = _refresh_job_status(
                _find_session_job(store, session_id, job_id), active
            )
            if job.get("status") != "running":
                return JobStopOutput(
                    job=_public_job(job), killed=False, stderr=""
                )
            managed = str(job.get("kind") or "shell") == "managed"
            shell_id = _job_shell_id(job)
            job["status"] = "stopping"
            job["updated_at"] = _utc()
            operation_id = _begin_job_operation(job, "stop")
    except BaseException:
        _ACTIVE_JOB_OPERATIONS.discard(operation_id)
        raise

    try:
        if managed:
            return await _stop_managed_job(session_id, job_id, operation_id)
        try:
            result = await kill_persistent_shell_execute(shell_id)
        except Exception as exc:
            still_active = True
            with contextlib.suppress(Exception):
                shells = await list_persistent_shells_execute()
                still_active = shell_id in _active_shell_ids(shells)
            with _store_transaction() as store:
                job = _find_session_job(store, session_id, job_id)
                if (
                    job.get("status") == "stopping"
                    and _job_shell_id(job) == shell_id
                    and _job_operation_matches(job, operation_id)
                ):
                    completed = _utc()
                    job["status"] = "running" if still_active else "lost"
                    job["updated_at"] = completed
                    job["error"] = (
                        f"stop failed: {public_error_type(exc)}: {exc}"
                    )
                    if not still_active:
                        job["completed_at"] = completed
                    _clear_job_operation(job)
            raise

        data = result.model_dump()
        killed = bool(data.get("killed"))
        stderr = str(data.get("stderr") or "")
        with _store_transaction() as store:
            job = _find_session_job(store, session_id, job_id)
            if (
                job.get("status") == "stopping"
                and _job_shell_id(job) == shell_id
                and _job_operation_matches(job, operation_id)
            ):
                completed = _utc()
                job.update(
                    {
                        "status": "stopped" if killed else "lost",
                        "updated_at": completed,
                        "completed_at": completed,
                        "exit_code": None,
                        "error": None
                        if killed
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
        _ACTIVE_JOB_OPERATIONS.discard(operation_id)


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
            paths = _attempt_paths(job_id, attempts)
            write_private_text(paths["log"], "")
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
        _ACTIVE_JOB_OPERATIONS.discard(operation_id)


async def job_retry_execute(session_id: str, job_id: str) -> JobRetryOutput:
    """Retry a terminal job with durable two-phase state transitions."""
    session = get_tool_session_store().touch_session(session_id)
    managed = job_id in managed_job_id_set(session_id, [job_id])
    if managed:
        return await _retry_managed_job(session_id, job_id)
    active = _active_shell_ids(await list_persistent_shells_execute())
    operation_id = ""
    try:
        with _store_transaction() as store:
            job = _refresh_job_status(
                _find_session_job(store, session_id, job_id), active
            )
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
        _ACTIVE_JOB_OPERATIONS.discard(operation_id)
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
                str(resolved_cwd), shell_name, runner_command
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
        _ACTIVE_JOB_OPERATIONS.discard(operation_id)


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


def _runner_shell_args(shell: str, command: str) -> list[str]:
    """Build direct subprocess arguments for the configured user shell."""
    name = Path(shell).name.lower()
    if name in {"powershell.exe", "powershell", "pwsh.exe", "pwsh"}:
        return [shell, "-NoProfile", "-NonInteractive", "-Command", command]
    if name in {"cmd.exe", "cmd"}:
        return [shell, "/D", "/S", "/C", command]
    return [shell, "-lc", command]


def _compact_log(handle: BinaryIO, max_bytes: int) -> bool:
    """Keep only the newest max_bytes of one open binary job log."""
    handle.flush()
    size = handle.tell()
    if size <= max_bytes:
        return False
    handle.seek(max(0, size - max_bytes))
    tail = handle.read(max_bytes)
    handle.seek(0)
    handle.truncate()
    handle.write(tail)
    handle.flush()
    return True


def run_job_runner_from_args(args: Any) -> None:
    """Run one internal durable job attempt and write its terminal status."""
    command_path = Path(args.command_file)
    log_path = Path(args.log_file)
    status_path = Path(args.status_file)
    cwd = Path(args.cwd)
    shell = str(args.shell)
    max_log_bytes = max(1, int(args.max_log_bytes))
    completed_at = _utc()
    exit_code: int | None = None
    error: str | None = None
    output_bytes = 0
    log_truncated = False
    process: subprocess.Popen[bytes] | None = None

    try:
        command = command_path.read_text(encoding="utf-8")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w+b") as log:
            with contextlib.suppress(OSError):
                log_path.chmod(0o600)
            process = subprocess.Popen(
                _runner_shell_args(shell, command),
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=_subprocess_env(),
            )
            if process.stdout is None:
                raise RuntimeError(
                    "job runner failed to capture process output"
                )
            read_available = getattr(
                process.stdout, "read1", process.stdout.read
            )
            while True:
                chunk = read_available(65536)
                if not chunk:
                    break
                output_bytes += len(chunk)
                log.write(chunk)
                log.flush()
                if log.tell() > max_log_bytes * 2:
                    log_truncated = (
                        _compact_log(log, max_log_bytes) or log_truncated
                    )
            exit_code = process.wait()
            log_truncated = _compact_log(log, max_log_bytes) or log_truncated
    except BaseException as exc:
        if process is not None and process.poll() is None:
            with contextlib.suppress(Exception):
                process.kill()
                process.wait(timeout=2)
        error = f"{public_error_type(exc)}: {exc}"
    finally:
        completed_at = _utc()
        atomic_write_private_text(
            status_path,
            json.dumps(
                {
                    "exit_code": exit_code,
                    "completed_at": completed_at,
                    "error": error,
                    "log_truncated": log_truncated,
                    "output_bytes": output_bytes,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )

    if error is not None:
        raise SystemExit(1)
    raise SystemExit(exit_code or 0)
