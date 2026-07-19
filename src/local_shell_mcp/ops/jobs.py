"""Durable tracked background-job helpers."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Generator
from pathlib import Path
from typing import Any, BinaryIO

from ..audit import audit
from ..config.settings import get_settings
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
    UnknownAgentSessionError,
    get_tool_session_store,
    resolve_session_path,
)
from .shell import (
    _subprocess_env,
    check_command_policy,
    kill_persistent_shell_execute,
    list_persistent_shells_execute,
    read_persistent_shell_output_execute,
    start_persistent_shell_execute,
)
from .utils.remote_session import call_remote_session_tool

JOB_STORE_FILE_NAME = "jobs.json"
JOB_STORE_BACKUP_FILE_NAME = "jobs.json.bak"
JOB_STORE_LOCK_FILE_NAME = "jobs.lock"
JOB_STORE_VERSION = 2
JOB_STORE_LEGACY_VERSIONS = {1}
TERMINAL_STATUSES = {"succeeded", "failed", "exited", "stopped", "lost"}
ACTIVE_STATUSES = {"starting", "running", "stopping", "retrying"}
_JOB_STORE_THREAD_LOCK = threading.RLock()
_ACTIVE_JOB_OPERATIONS: set[str] = set()


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


def _empty_store() -> dict[str, Any]:
    return {"version": JOB_STORE_VERSION, "jobs": []}


def _lock_store_file(handle: BinaryIO) -> None:
    """Acquire an exclusive one-byte file lock on every supported platform."""
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_store_file(handle: BinaryIO) -> None:
    """Release the cross-platform tracked-job file lock."""
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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


def _private_write_text(path: Path, content: str) -> None:
    """Write one private UTF-8 runtime file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    with contextlib.suppress(OSError):
        path.chmod(0o600)


def _private_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write one private JSON runtime file."""
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        _private_write_text(
            temporary,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )
        os.replace(temporary, path)
        with contextlib.suppress(OSError):
            path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


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
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(store, indent=2, sort_keys=True)
    tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    backup_tmp_path = backup_path.with_name(
        f"{backup_path.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        for temporary in (tmp_path, backup_tmp_path):
            _private_write_text(temporary, payload)
        os.replace(tmp_path, path)
        os.replace(backup_tmp_path, backup_path)
    finally:
        tmp_path.unlink(missing_ok=True)
        backup_tmp_path.unlink(missing_ok=True)


@contextlib.contextmanager
def _store_transaction() -> Generator[dict[str, Any]]:
    """Serialize one complete job-store read/modify/write transaction."""
    with _JOB_STORE_THREAD_LOCK:
        lock_path = _job_store_lock_path()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            with contextlib.suppress(OSError):
                lock_path.chmod(0o600)
            _lock_store_file(handle)
            try:
                store = _load_store()
                yield store
                _save_store(store)
            finally:
                _unlock_store_file(handle)


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
    _private_write_text(paths["command"], command)
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
            "name": str(job.get("name") or job.get("job_id") or ""),
            "status": str(job.get("status") or "unknown"),
            "command": str(job.get("command") or ""),
            "cwd": str(job.get("cwd") or "."),
            "session_id": str(job.get("session_id") or ""),
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
                            "error": f"start failed: {type(exc).__name__}: {exc}",
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
    active = _active_shell_ids(await list_persistent_shells_execute())
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


async def job_stop_execute(session_id: str, job_id: str) -> JobStopOutput:
    """Stop one tracked command through a serialized lifecycle transition."""
    get_tool_session_store().touch_session(session_id)
    active = _active_shell_ids(await list_persistent_shells_execute())
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
            shell_id = _job_shell_id(job)
            job["status"] = "stopping"
            job["updated_at"] = _utc()
            operation_id = _begin_job_operation(job, "stop")
    except BaseException:
        _ACTIVE_JOB_OPERATIONS.discard(operation_id)
        raise

    try:
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
                    job["error"] = f"stop failed: {type(exc).__name__}: {exc}"
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


async def job_retry_execute(session_id: str, job_id: str) -> JobRetryOutput:
    """Retry a terminal job with durable two-phase state transitions."""
    session = get_tool_session_store().touch_session(session_id)
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
                            "error": f"retry failed: {type(exc).__name__}: {exc}",
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


async def job_execute(
    session_id: str,
    list_jobs: bool = False,
    poll: list[str] | None = None,
    cancel: list[str] | None = None,
    retry: list[str] | None = None,
    include_finished: bool = True,
    lines: int = 200,
) -> JobOutput:
    """Run one high-level tracked-job companion operation."""
    try:
        session = get_tool_session_store().touch_session(session_id)
    except UnknownAgentSessionError:
        session = None
    if session is not None and session.target == "remote":
        data = await call_remote_session_tool(
            session,
            "job",
            {
                "list_jobs": list_jobs,
                "poll": poll,
                "cancel": cancel,
                "retry": retry,
                "include_finished": include_finished,
                "lines": lines,
            },
        )
        return JobOutput.model_validate(data)

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
                "No tracked bash jobs in this session."
                if not result.jobs
                else "Tracked bash job snapshot for this session."
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
        error = f"{type(exc).__name__}: {exc}"
    finally:
        completed_at = _utc()
        _private_write_json(
            status_path,
            {
                "exit_code": exit_code,
                "completed_at": completed_at,
                "error": error,
                "log_truncated": log_truncated,
                "output_bytes": output_bytes,
            },
        )

    if error is not None:
        raise SystemExit(1)
    raise SystemExit(exit_code or 0)
