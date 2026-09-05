"""Session-retention policy and durable-job protection discovery."""

from pathlib import Path
from typing import Any

from ..persistence import StateStore
from ..utils.runtime_identity import managed_job_lease_state
from .records import AgentSession, valid_session_id

JOB_STORE_READ_MAX_BYTES = 64 * 1024 * 1024
ACTIVE_JOB_STATUSES = {"starting", "running", "stopping", "retrying"}


class JobProtectionReader:
    """Discover sessions conservatively protected by durable tracked jobs."""

    def __init__(
        self, state_store: StateStore, *, status_max_bytes: int
    ) -> None:
        self._state_store = state_store
        self._status_max_bytes = status_max_bytes

    def active_session_ids(self) -> set[str] | None:
        """Return job-protected session ids, or None when job state is uncertain."""
        primary = self._state_store.layout.jobs_store_path
        backup = self._state_store.layout.jobs_store_backup_path
        if not primary.exists() and not backup.exists():
            return set()

        payload: dict[str, Any] | None = None
        for path in (primary, backup):
            if not path.exists():
                continue
            try:
                candidate = self._state_store.read_json(
                    path,
                    max_bytes=JOB_STORE_READ_MAX_BYTES,
                )
            except OSError, TypeError, ValueError:
                continue
            if isinstance(candidate, dict) and isinstance(
                candidate.get("jobs"), list
            ):
                payload = candidate
                break
        if payload is None:
            return None

        protected: set[str] = set()
        for job in payload["jobs"]:
            if not isinstance(job, dict):
                continue
            session_id = valid_session_id(job.get("session_id"))
            status = str(job.get("status") or "")
            kind = str(job.get("kind") or "shell")
            protective_status = status in ACTIVE_JOB_STATUSES or (
                kind == "shell"
                and status == "lost"
                and not bool(job.get("shell_absence_confirmed"))
            )
            managed_owner_state = (
                managed_job_lease_state(
                    str(job.get("job_id") or ""),
                    job.get("managed_lease_version"),
                )
                if kind == "managed"
                else "live"
            )
            if (
                session_id is not None
                and protective_status
                and managed_owner_state != "dead"
                and not self._has_durable_completion(job, status)
            ):
                protected.add(session_id)
                if kind == "managed":
                    protected.update(
                        self._managed_payload_session_ids(
                            job.get("managed_payload")
                        )
                    )
        return protected

    def _managed_payload_session_ids(self, payload: Any) -> set[str]:
        """Return existing agent sessions referenced by managed-job payloads."""
        protected: set[str] = set()
        pending = [payload]
        while pending:
            current = pending.pop()
            if isinstance(current, dict):
                for key, value in current.items():
                    if isinstance(key, str) and (
                        key == "session_id" or key.endswith("_session_id")
                    ):
                        session_id = valid_session_id(value)
                        if (
                            session_id is not None
                            and self._state_store.layout.session_metadata_path(
                                session_id
                            ).exists()
                        ):
                            protected.add(session_id)
                    if isinstance(value, dict | list):
                        pending.append(value)
            elif isinstance(current, list):
                pending.extend(current)
        return protected

    def _has_durable_completion(self, job: dict[str, Any], status: str) -> bool:
        """Return whether the runner already persisted terminal job metadata."""
        status_key = (
            "pending_status_path" if status == "retrying" else "status_path"
        )
        raw_path = job.get(status_key)
        if not raw_path:
            return False
        try:
            payload = self._state_store.read_json(
                Path(str(raw_path)), max_bytes=self._status_max_bytes
            )
        except OSError, TypeError, ValueError:
            return False
        return isinstance(payload, dict)


def session_has_active_jobs(
    session_id: str, active_job_session_ids: set[str] | None
) -> bool:
    """Conservatively treat unreadable durable-job state as active ownership."""
    return (
        active_job_session_ids is None or session_id in active_job_session_ids
    )


def session_expired_by_policy(
    session: AgentSession, now: float, retention_s: int
) -> bool:
    """Return expiry before persistent-resource and durable-job protection."""
    return (session.expires_at is not None and session.expires_at <= now) or (
        retention_s > 0 and session.updated_at < now - retention_s
    )


def expired_prune_eligible(
    session: AgentSession,
    now: float,
    retention_s: int,
    active_job_session_ids: set[str] | None,
) -> bool:
    """Return whether one freshly loaded session may be expiry-pruned."""
    return (
        session.target == "local"
        and session_expired_by_policy(session, now, retention_s)
        and not session.persistent_shell_ids
        and not session_has_active_jobs(
            session.session_id, active_job_session_ids
        )
    )


def overflow_prune_eligible(
    session: AgentSession,
    now: float,
    active_job_session_ids: set[str] | None,
    *,
    active_window_s: int,
) -> bool:
    """Return whether one freshly loaded session may be capacity-pruned."""
    return (
        session.target == "local"
        and session.updated_at < now - active_window_s
        and not session.persistent_shell_ids
        and not session_has_active_jobs(
            session.session_id, active_job_session_ids
        )
    )
