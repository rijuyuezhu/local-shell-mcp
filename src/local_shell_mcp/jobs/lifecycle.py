"""Shell-attempt materialization and durable job-status reconciliation."""

import json
import re
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..config.settings import get_settings
from ..ops.shell import check_command_policy
from ..utils.private_files import write_private_text
from .persistence import attempt_paths as _attempt_paths
from .state import (
    ACTIVE_STATUSES,
)
from .state import (
    clear_job_operation as _clear_job_operation,
)
from .state import (
    job_operation_is_active as _job_operation_is_active,
)
from .state import (
    job_shell_id as _job_shell_id,
)
from .state import (
    utc as _utc,
)

type ManagedJobStateProbe = Callable[[dict[str, Any]], bool]
type ManagedJobLivenessProbe = Callable[[dict[str, Any]], str]
type JobStatusReader = Callable[[dict[str, Any]], dict[str, Any] | None]
type JobStatusPathReader = Callable[[Any], dict[str, Any] | None]


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
    *,
    managed_job_has_local_task: ManagedJobStateProbe,
    managed_job_liveness: ManagedJobLivenessProbe,
    read_status: JobStatusReader = _read_status,
    read_status_path: JobStatusPathReader = _read_status_path,
) -> dict[str, Any]:
    """Apply durable completion and authoritative live-shell reconciliation."""
    status = str(job.get("status") or "unknown")
    kind = str(job.get("kind") or "shell")
    if status == "lost" and kind == "shell":
        updated = now or _utc()
        status_payload = read_status(job)
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
        if managed_job_has_local_task(job):
            return job
        liveness = managed_job_liveness(job)
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
        status_payload = read_status(job)
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
        status_payload = read_status_path(job.get("pending_status_path"))
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

    status_payload = read_status(job)
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
