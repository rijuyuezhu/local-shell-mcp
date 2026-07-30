"""Durable state for explicit agent/workspace sessions and grounding snapshots."""

import hashlib
import json
import secrets
import string
import threading
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal, cast

from ..config.settings import get_settings
from ..ops.utils.path import resolve_path
from ..persistence import StateStore, get_state_store
from ..utils.runtime_identity import PROCESS_INSTANCE_ID

SESSION_ID_ALPHABET = string.ascii_letters + string.digits
SESSION_ID_LENGTH = 8
SESSION_METADATA_MAX_BYTES = 256_000
SESSION_SNAPSHOTS_MAX_BYTES = 16_000_000
SESSION_ACTIVE_WINDOW_S = 5 * 60 * 60
JOB_STORE_READ_MAX_BYTES = 64 * 1024 * 1024
ACTIVE_JOB_STATUSES = {"starting", "running", "stopping", "retrying"}
SESSION_TERMINATION_PROMPT = (
    "This session was marked for immediate termination by the human control "
    "plane. Stop immediately. Do not perform any further work or call any more "
    "tools for this session. Tell the user that execution was terminated by "
    "the human operator."
)
type SessionTarget = Literal["local", "remote"]


@dataclass(frozen=True)
class AgentSession:
    """One explicit agent workspace session."""

    session_id: str
    """Opaque 8-character alphanumeric session id returned to the agent."""

    target: SessionTarget
    """Execution target bound to this session."""

    workdir: str
    """Canonical workdir bound to this session."""

    machine: str | None
    """Remote worker machine name for remote sessions."""

    worker_session_id: str | None
    """Worker-side paired session id for remote sessions."""

    created_at: float
    """Unix timestamp when this session was created."""

    updated_at: float
    """Unix timestamp when this session was last touched."""

    expires_at: float | None = None
    """Optional Unix timestamp when this session expires."""

    label: str | None = None
    """Optional human-readable session label."""

    termination_requested_at: float | None = None
    """Unix timestamp when the human control plane requested immediate stop."""

    persistent_shell_ids: tuple[str, ...] = ()
    """Durable local PTY ids that must keep this session from being pruned."""


@dataclass(frozen=True)
class SnapshotRecord:
    """One displayed file snapshot recorded for stale-edit checks."""

    session_id: str
    """Agent grounding session that owns this snapshot."""

    snapshot_id: str
    """Opaque snapshot handle returned to the agent."""

    path: str
    """Workspace-relative file path displayed to the agent."""

    file_sha256: str
    """SHA-256 digest of the complete file when displayed."""

    total_lines: int
    """Decoded line count at the time this snapshot was displayed."""

    seen_ranges: tuple[tuple[int, int], ...]
    """Inclusive 1-based line ranges that were actually displayed."""

    created_at: float
    """Unix timestamp when this snapshot was recorded."""

    sequence: int = 0
    """Durable insertion sequence used to break equal timestamp ties."""


def generate_session_id() -> str:
    """Return one opaque 8-character alphanumeric agent session id."""
    return "".join(
        secrets.choice(SESSION_ID_ALPHABET) for _ in range(SESSION_ID_LENGTH)
    )


def _valid_session_id(value: Any) -> str | None:
    """Return one normalized agent session id, or None for invalid input."""
    if not isinstance(value, str):
        return None
    if len(value) != SESSION_ID_LENGTH or any(
        character not in SESSION_ID_ALPHABET for character in value
    ):
        return None
    return value


def _new_snapshot_id() -> str:
    """Return an opaque snapshot id for one displayed file view."""
    return secrets.token_hex(6)


class UnknownAgentSessionError(ValueError):
    """Raised when a tool call references a missing agent session."""


class ExpiredAgentSessionError(UnknownAgentSessionError):
    """Raised when a durable agent session has passed its retention boundary."""


class SessionTerminationRequestedError(ValueError):
    """Raised when a model invokes a tool for a terminated session."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"Session {session_id}: {SESSION_TERMINATION_PROMPT}")


class ToolSessionStore:
    """Persist explicit agent sessions and their grounding snapshots."""

    def __init__(self, state_store: StateStore | None = None) -> None:
        self._lock = threading.RLock()
        self._state_store = state_store or get_state_store()
        self._loaded_root: Path | None = None
        self._sessions: dict[str, AgentSession] = {}
        self._snapshots: dict[tuple[str, str], SnapshotRecord] = {}

    @staticmethod
    def _required_float(payload: dict[str, Any], field: str) -> float:
        candidate = payload.get(field)
        if isinstance(candidate, bool) or not isinstance(
            candidate, int | float
        ):
            raise ValueError(f"metadata contains an invalid {field}")
        return float(candidate)

    @staticmethod
    def _required_int(payload: dict[str, Any], field: str) -> int:
        candidate = payload.get(field)
        if isinstance(candidate, bool) or not isinstance(candidate, int):
            raise ValueError(f"metadata contains an invalid {field}")
        return candidate

    @staticmethod
    def _session_from_payload(value: Any) -> AgentSession:
        if not isinstance(value, dict):
            raise ValueError("session metadata must be a JSON object")
        payload = cast(dict[str, Any], value)
        session_id = _valid_session_id(payload.get("session_id"))
        if session_id is None:
            raise ValueError("session metadata contains an invalid session_id")
        target_value = str(payload.get("target") or "")
        if target_value not in {"local", "remote"}:
            raise ValueError("session metadata contains an invalid target")
        target = cast(SessionTarget, target_value)
        workdir = str(payload.get("workdir") or "")
        if not workdir:
            raise ValueError("session metadata contains an empty workdir")
        machine = payload.get("machine")
        worker_session_id = payload.get("worker_session_id")
        if target == "local":
            machine = None
            worker_session_id = None
        elif not machine or not worker_session_id:
            raise ValueError(
                "remote session metadata is missing its worker binding"
            )
        shell_ids = payload.get("persistent_shell_ids", [])
        if not isinstance(shell_ids, list):
            raise ValueError(
                "session metadata contains invalid persistent_shell_ids"
            )
        normalized_shell_ids = tuple(
            dict.fromkeys(str(shell_id) for shell_id in shell_ids if shell_id)
        )
        if target == "remote":
            normalized_shell_ids = ()
        return AgentSession(
            session_id=session_id,
            target=target,
            workdir=workdir,
            machine=None if machine is None else str(machine),
            worker_session_id=(
                None if worker_session_id is None else str(worker_session_id)
            ),
            created_at=ToolSessionStore._required_float(payload, "created_at"),
            updated_at=ToolSessionStore._required_float(payload, "updated_at"),
            expires_at=(
                None
                if payload.get("expires_at") is None
                else ToolSessionStore._required_float(payload, "expires_at")
            ),
            label=(
                None if payload.get("label") is None else str(payload["label"])
            ),
            termination_requested_at=(
                None
                if payload.get("termination_requested_at") is None
                else ToolSessionStore._required_float(
                    payload, "termination_requested_at"
                )
            ),
            persistent_shell_ids=normalized_shell_ids,
        )

    @staticmethod
    def _snapshot_from_payload(
        value: Any, *, fallback_sequence: int = 0
    ) -> SnapshotRecord:
        if not isinstance(value, dict):
            raise ValueError("snapshot metadata must be a JSON object")
        payload = cast(dict[str, Any], value)
        ranges = payload.get("seen_ranges")
        if not isinstance(ranges, list):
            raise ValueError("snapshot metadata contains invalid seen_ranges")
        normalized_ranges: list[tuple[int, int]] = []
        for item in ranges:
            if not isinstance(item, list | tuple) or len(item) != 2:
                raise ValueError("snapshot metadata contains an invalid range")
            normalized_ranges.append((int(item[0]), int(item[1])))
        sequence = (
            fallback_sequence
            if payload.get("sequence") is None
            else ToolSessionStore._required_int(payload, "sequence")
        )
        if sequence < 0:
            raise ValueError("snapshot metadata contains invalid sequence")
        return SnapshotRecord(
            session_id=str(payload.get("session_id") or ""),
            snapshot_id=str(payload.get("snapshot_id") or ""),
            path=str(payload.get("path") or ""),
            file_sha256=str(payload.get("file_sha256") or ""),
            total_lines=ToolSessionStore._required_int(payload, "total_lines"),
            seen_ranges=tuple(normalized_ranges),
            created_at=ToolSessionStore._required_float(payload, "created_at"),
            sequence=sequence,
        )

    def _reset_for_current_root_locked(self) -> None:
        root = self._state_store.layout.root
        if self._loaded_root == root:
            return
        self._sessions.clear()
        self._snapshots.clear()
        self._loaded_root = root

    def _metadata_path(self, session_id: str) -> Path:
        return self._state_store.layout.session_metadata_path(session_id)

    def _snapshots_path(self, session_id: str) -> Path:
        return self._state_store.layout.session_snapshots_path(session_id)

    def _transaction_path(self, session_id: str) -> Path:
        return self._state_store.layout.session_transaction_path(session_id)

    def _remove_session_state_locked(self, session_id: str) -> None:
        """Remove one session directory and all process-local cached state."""
        self._state_store.remove(
            self._state_store.layout.session_dir(session_id),
            recursive=True,
        )
        self._sessions.pop(session_id, None)
        self._snapshots = {
            key: value
            for key, value in self._snapshots.items()
            if key[0] != session_id
        }

    def _managed_payload_session_ids_locked(self, payload: Any) -> set[str]:
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
                        session_id = _valid_session_id(value)
                        if (
                            session_id is not None
                            and self._metadata_path(session_id).exists()
                        ):
                            protected.add(session_id)
                    if isinstance(value, dict | list):
                        pending.append(value)
            elif isinstance(current, list):
                pending.extend(current)
        return protected

    def _active_job_session_ids_locked(self) -> set[str] | None:
        """Load sessions protected by active durable jobs, or None if uncertain."""
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
            session_id = _valid_session_id(job.get("session_id"))
            status = str(job.get("status") or "")
            kind = str(job.get("kind") or "shell")
            protective_status = status in ACTIVE_JOB_STATUSES or (
                kind == "shell"
                and status == "lost"
                and not bool(job.get("shell_absence_confirmed"))
            )
            if (
                session_id is not None
                and protective_status
                and (
                    kind != "managed"
                    or str(job.get("runtime_instance_id") or "")
                    == PROCESS_INSTANCE_ID
                )
                and not self._job_has_durable_completion_locked(job, status)
            ):
                protected.add(session_id)
                if kind == "managed":
                    protected.update(
                        self._managed_payload_session_ids_locked(
                            job.get("managed_payload")
                        )
                    )
        return protected

    def _job_has_durable_completion_locked(
        self, job: dict[str, Any], status: str
    ) -> bool:
        """Return whether the runner already persisted terminal job metadata."""
        status_key = (
            "pending_status_path" if status == "retrying" else "status_path"
        )
        raw_path = job.get(status_key)
        if not raw_path:
            return False
        try:
            payload = self._state_store.read_json(
                Path(str(raw_path)), max_bytes=SESSION_METADATA_MAX_BYTES
            )
        except OSError, TypeError, ValueError:
            return False
        return isinstance(payload, dict)

    @staticmethod
    def _session_has_active_jobs(
        session_id: str, active_job_session_ids: set[str] | None
    ) -> bool:
        """Conservatively treat an unreadable jobs store as active participation."""
        return (
            active_job_session_ids is None
            or session_id in active_job_session_ids
        )

    def _session_has_active_jobs_locked(self, session_id: str) -> bool:
        """Conservatively protect one session participating in durable jobs."""
        return self._session_has_active_jobs(
            session_id, self._active_job_session_ids_locked()
        )

    @staticmethod
    def _session_expired_by_policy(
        session: AgentSession, now: float, retention_s: int
    ) -> bool:
        """Return expiry before active-job ownership is considered."""
        return (
            session.expires_at is not None and session.expires_at <= now
        ) or (retention_s > 0 and session.updated_at < now - retention_s)

    def _session_expired(self, session: AgentSession, now: float) -> bool:
        """Return whether explicit expiry or idle retention invalidates a session."""
        retention_s = int(get_settings().agent_session_retention_s)
        return (
            self._session_expired_by_policy(session, now, retention_s)
            and not session.persistent_shell_ids
            and not self._session_has_active_jobs_locked(session.session_id)
        )

    def _read_all_sessions_locked(self) -> dict[str, AgentSession]:
        """Load valid durable session metadata without applying retention."""
        sessions: dict[str, AgentSession] = {}
        for directory in self._state_store.iter_directories(
            self._state_store.layout.sessions_dir
        ):
            try:
                session = self._session_from_payload(
                    self._state_store.read_json(
                        directory / "session.json",
                        max_bytes=SESSION_METADATA_MAX_BYTES,
                    )
                )
            except OSError, TypeError, ValueError:
                continue
            if session.session_id == directory.name:
                sessions[session.session_id] = session
        return sessions

    def _expired_prune_eligible_locked(
        self,
        session: AgentSession,
        now: float,
        retention_s: int,
        active_job_session_ids: set[str] | None,
    ) -> bool:
        """Return whether a freshly loaded session remains expiry-eligible."""
        return (
            session.target == "local"
            and self._session_expired_by_policy(session, now, retention_s)
            and not session.persistent_shell_ids
            and not self._session_has_active_jobs(
                session.session_id, active_job_session_ids
            )
        )

    def _overflow_prune_eligible_locked(
        self,
        session: AgentSession,
        now: float,
        active_job_session_ids: set[str] | None,
    ) -> bool:
        """Return whether a freshly loaded session remains overflow-eligible."""
        return (
            session.target == "local"
            and session.updated_at < now - SESSION_ACTIVE_WINDOW_S
            and not session.persistent_shell_ids
            and not self._session_has_active_jobs(
                session.session_id, active_job_session_ids
            )
        )

    def _prune_sessions_locked(
        self, now: float, *, reserve_slots: int = 0
    ) -> list[AgentSession]:
        """Remove expired sessions and inactive overflow beyond the configured cap."""
        sessions = self._read_all_sessions_locked()
        active_job_session_ids = self._active_job_session_ids_locked()
        retention_s = int(get_settings().agent_session_retention_s)
        expired = [
            session
            for session in sessions.values()
            if self._expired_prune_eligible_locked(
                session, now, retention_s, active_job_session_ids
            )
        ]
        for session in expired:
            with (
                self._state_store.transaction(
                    self._transaction_path(session.session_id)
                ),
                self._state_store.transaction(
                    self._state_store.layout.jobs_lock_path
                ),
            ):
                current = self._load_session_locked(session.session_id)
                if current is None:
                    sessions.pop(session.session_id, None)
                    continue
                current_jobs = self._active_job_session_ids_locked()
                if not self._expired_prune_eligible_locked(
                    current, now, retention_s, current_jobs
                ):
                    sessions[session.session_id] = current
                    continue
                self._remove_session_state_locked(session.session_id)
                sessions.pop(session.session_id, None)

        sessions = self._read_all_sessions_locked()
        maximum = int(get_settings().max_agent_sessions)
        target = max(0, maximum - max(0, reserve_slots))
        overflow = max(0, len(sessions) - target)
        if overflow:
            inactive = sorted(
                (
                    session
                    for session in sessions.values()
                    if session.target == "local"
                    and session.updated_at < now - SESSION_ACTIVE_WINDOW_S
                    and not session.persistent_shell_ids
                    and not self._session_has_active_jobs(
                        session.session_id, active_job_session_ids
                    )
                ),
                key=lambda session: (session.updated_at, session.created_at),
            )
            for session in inactive:
                with (
                    self._state_store.transaction(
                        self._transaction_path(session.session_id)
                    ),
                    self._state_store.transaction(
                        self._state_store.layout.jobs_lock_path
                    ),
                ):
                    current_sessions = self._read_all_sessions_locked()
                    if len(current_sessions) <= target:
                        sessions = current_sessions
                        break
                    current = current_sessions.get(session.session_id)
                    if current is None:
                        sessions = current_sessions
                        continue
                    current_jobs = self._active_job_session_ids_locked()
                    if not self._overflow_prune_eligible_locked(
                        current, now, current_jobs
                    ):
                        sessions = current_sessions
                        continue
                    self._remove_session_state_locked(session.session_id)
                    current_sessions.pop(session.session_id, None)
                    sessions = current_sessions

        self._sessions = sessions
        return sorted(
            sessions.values(),
            key=lambda session: (session.updated_at, session.created_at),
            reverse=True,
        )

    def _load_session_locked(self, session_id: str) -> AgentSession | None:
        value = self._state_store.read_json(
            self._metadata_path(session_id),
            max_bytes=SESSION_METADATA_MAX_BYTES,
        )
        if value is None:
            self._sessions.pop(session_id, None)
            return None
        session = self._session_from_payload(value)
        if session.session_id != session_id:
            raise ValueError("session directory and metadata id do not match")
        self._sessions[session_id] = session
        return session

    def _require_session_locked(
        self, session_id: str, *, allow_expired: bool = False
    ) -> AgentSession:
        session = self._load_session_locked(session_id)
        if session is None:
            raise UnknownAgentSessionError(
                f"unknown session_id {session_id!r}; call session_start first"
            )
        if not allow_expired and self._session_expired(session, time.time()):
            if session.target == "local":
                self._remove_session_state_locked(session_id)
            raise ExpiredAgentSessionError(
                f"expired session_id {session_id!r}; "
                + (
                    "call session_end to release its remote worker binding"
                    if session.target == "remote"
                    else "call session_start again"
                )
            )
        return session

    def _load_snapshots_locked(self, session_id: str) -> None:
        self._snapshots = {
            key: value
            for key, value in self._snapshots.items()
            if key[0] != session_id
        }
        payload = self._state_store.read_json(
            self._snapshots_path(session_id),
            max_bytes=SESSION_SNAPSHOTS_MAX_BYTES,
        )
        if payload is None:
            return
        if not isinstance(payload, dict) or not isinstance(
            payload.get("snapshots"), list
        ):
            raise ValueError("session snapshots must contain a snapshots array")
        for sequence, value in enumerate(payload["snapshots"], start=1):
            snapshot = self._snapshot_from_payload(
                value, fallback_sequence=sequence
            )
            if snapshot.session_id != session_id:
                raise ValueError(
                    "snapshot owner does not match its session directory"
                )
            self._snapshots[(session_id, snapshot.snapshot_id)] = snapshot

    def _write_session_locked(self, session: AgentSession) -> None:
        self._state_store.write_json(
            self._metadata_path(session.session_id), asdict(session)
        )

    def _write_snapshots_locked(self, session_id: str) -> None:
        snapshots = [
            asdict(snapshot)
            for (owner, _), snapshot in self._snapshots.items()
            if owner == session_id
        ]
        path = self._snapshots_path(session_id)
        if not snapshots:
            self._state_store.remove(path)
            return
        self._state_store.write_json(path, {"snapshots": snapshots})

    @staticmethod
    def _encoded_snapshot_payload_bytes(
        snapshots: list[SnapshotRecord],
    ) -> int:
        """Return exact bytes produced by StateStore.write_json for snapshots."""
        encoded = json.dumps(
            {"snapshots": [asdict(snapshot) for snapshot in snapshots]},
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        return len((encoded + "\n").encode("utf-8"))

    def _prune_snapshots_locked(self, session_id: str) -> None:
        """Keep the newest per-session snapshots within count and byte limits."""
        settings = get_settings()
        snapshots = sorted(
            (
                snapshot
                for (owner, _), snapshot in self._snapshots.items()
                if owner == session_id
            ),
            key=lambda snapshot: (snapshot.created_at, snapshot.sequence),
            reverse=True,
        )[: int(settings.max_session_snapshots)]
        maximum_bytes = int(settings.max_session_snapshot_bytes)
        low = 0
        high = len(snapshots)
        while low < high:
            middle = (low + high + 1) // 2
            if (
                self._encoded_snapshot_payload_bytes(snapshots[:middle])
                <= maximum_bytes
            ):
                low = middle
            else:
                high = middle - 1
        kept = snapshots[:low]
        self._snapshots = {
            key: value
            for key, value in self._snapshots.items()
            if key[0] != session_id
        }
        self._snapshots.update(
            {(session_id, snapshot.snapshot_id): snapshot for snapshot in kept}
        )

    def create_session(
        self,
        *,
        target: SessionTarget = "local",
        workdir: str | Path = ".",
        machine: str | None = None,
        worker_session_id: str | None = None,
        label: str | None = None,
        expires_at: float | None = None,
    ) -> AgentSession:
        """Create and durably store one explicit agent workspace session."""
        if target == "local":
            resolved_workdir = resolve_path(workdir, must_exist=True)
            if not resolved_workdir.is_dir():
                raise NotADirectoryError(str(resolved_workdir))
            display_workdir = str(resolved_workdir)
            normalized_machine = None
            normalized_worker_session_id = None
        elif target == "remote":
            if not machine:
                raise ValueError("machine is required for remote sessions")
            display_workdir = str(workdir)
            normalized_machine = machine
            normalized_worker_session_id = worker_session_id
        else:
            raise ValueError(f"unsupported session target: {target!r}")

        with self._lock:
            self._reset_for_current_root_locked()
            registry = self._state_store.layout.sessions_dir / ".registry"
            with self._state_store.transaction(registry):
                now = time.time()
                sessions = self._prune_sessions_locked(now, reserve_slots=1)
                maximum = int(get_settings().max_agent_sessions)
                if len(sessions) >= maximum:
                    raise RuntimeError(
                        "agent session limit reached: "
                        f"{maximum}; end an active session or wait for retention cleanup"
                    )
                for _ in range(16):
                    session_id = generate_session_id()
                    if not self._metadata_path(session_id).exists():
                        break
                else:
                    raise RuntimeError("failed to allocate a unique session_id")
                session = AgentSession(
                    session_id=session_id,
                    target=target,
                    workdir=display_workdir,
                    machine=normalized_machine,
                    worker_session_id=normalized_worker_session_id,
                    created_at=now,
                    updated_at=now,
                    expires_at=expires_at,
                    label=label,
                    termination_requested_at=None,
                    persistent_shell_ids=(),
                )
                with self._state_store.transaction(
                    self._transaction_path(session_id)
                ):
                    self._write_session_locked(session)
                    self._sessions[session_id] = session
                    return session

    def require_session(self, session_id: str) -> AgentSession:
        """Return an existing durable session or raise a clear error."""
        with self._lock:
            self._reset_for_current_root_locked()
            with self._state_store.transaction(
                self._transaction_path(session_id)
            ):
                return self._require_session_locked(session_id)

    def prepare_session_termination(self, session_id: str) -> AgentSession:
        """Make a known session cleanup-only even after its expiry boundary."""
        with self._lock:
            self._reset_for_current_root_locked()
            with self._state_store.transaction(
                self._transaction_path(session_id)
            ):
                session = self._require_session_locked(
                    session_id, allow_expired=True
                )
                now = time.time()
                updated = replace(
                    session,
                    updated_at=now,
                    expires_at=None,
                    termination_requested_at=(
                        session.termination_requested_at or now
                    ),
                )
                self._write_session_locked(updated)
                self._sessions[session_id] = updated
                return updated

    def touch_session(self, session_id: str) -> AgentSession:
        """Refresh a session's durable updated timestamp."""
        with self._lock:
            self._reset_for_current_root_locked()
            with self._state_store.transaction(
                self._transaction_path(session_id)
            ):
                session = self._require_session_locked(session_id)
                updated = replace(session, updated_at=time.time())
                self._write_session_locked(updated)
                self._sessions[session_id] = updated
                return updated

    def register_persistent_shell(
        self, session_id: str, shell_id: str
    ) -> AgentSession:
        """Durably bind one local persistent shell to its owning session."""
        normalized_shell_id = str(shell_id).strip()
        if not normalized_shell_id:
            raise ValueError("shell_id must not be empty")
        with self._lock:
            self._reset_for_current_root_locked()
            with self._state_store.transaction(
                self._transaction_path(session_id)
            ):
                session = self._require_session_locked(session_id)
                if session.target != "local":
                    raise ValueError(
                        "persistent shells require a local session"
                    )
                updated = replace(
                    session,
                    updated_at=time.time(),
                    persistent_shell_ids=tuple(
                        dict.fromkeys(
                            (*session.persistent_shell_ids, normalized_shell_id)
                        )
                    ),
                )
                self._write_session_locked(updated)
                self._sessions[session_id] = updated
                return updated

    def release_persistent_shell(self, shell_id: str) -> None:
        """Remove one persistent shell id from every durable local session."""
        normalized_shell_id = str(shell_id).strip()
        if not normalized_shell_id:
            return
        with self._lock:
            self._reset_for_current_root_locked()
            sessions = self._read_all_sessions_locked()
            for session in sessions.values():
                if normalized_shell_id not in session.persistent_shell_ids:
                    continue
                with self._state_store.transaction(
                    self._transaction_path(session.session_id)
                ):
                    current = self._load_session_locked(session.session_id)
                    if current is None:
                        continue
                    updated = replace(
                        current,
                        persistent_shell_ids=tuple(
                            existing
                            for existing in current.persistent_shell_ids
                            if existing != normalized_shell_id
                        ),
                    )
                    self._write_session_locked(updated)
                    self._sessions[session.session_id] = updated

    def reconcile_session_persistent_shells(
        self, session_id: str, owned_shell_ids: set[str]
    ) -> AgentSession:
        """Replace one session's durable PTY ids with authoritative ownership."""
        normalized = tuple(
            sorted(
                {
                    str(shell_id).strip()
                    for shell_id in owned_shell_ids
                    if str(shell_id).strip()
                }
            )
        )
        with self._lock:
            self._reset_for_current_root_locked()
            with self._state_store.transaction(
                self._transaction_path(session_id)
            ):
                current = self._require_session_locked(
                    session_id, allow_expired=True
                )
                if current.target != "local":
                    raise ValueError(
                        "persistent shells require a local session"
                    )
                if current.persistent_shell_ids == normalized:
                    return current
                updated = replace(current, persistent_shell_ids=normalized)
                self._write_session_locked(updated)
                self._sessions[session_id] = updated
                return updated

    def reconcile_persistent_shells(self, live_shell_ids: set[str]) -> None:
        """Discard durable PTY ownership entries whose shell no longer exists."""
        live = {str(shell_id) for shell_id in live_shell_ids if shell_id}
        with self._lock:
            self._reset_for_current_root_locked()
            sessions = self._read_all_sessions_locked()
            for session in sessions.values():
                if all(
                    shell_id in live
                    for shell_id in session.persistent_shell_ids
                ):
                    continue
                with self._state_store.transaction(
                    self._transaction_path(session.session_id)
                ):
                    current = self._load_session_locked(session.session_id)
                    if current is None:
                        continue
                    retained = tuple(
                        shell_id
                        for shell_id in current.persistent_shell_ids
                        if shell_id in live
                    )
                    if retained == current.persistent_shell_ids:
                        continue
                    updated = replace(current, persistent_shell_ids=retained)
                    self._write_session_locked(updated)
                    self._sessions[session.session_id] = updated

    def request_termination(self, session_id: str) -> AgentSession:
        """Persist an irreversible immediate-stop request for one session."""
        with self._lock:
            self._reset_for_current_root_locked()
            with self._state_store.transaction(
                self._transaction_path(session_id)
            ):
                session = self._require_session_locked(session_id)
                now = time.time()
                updated = replace(
                    session,
                    updated_at=now,
                    termination_requested_at=(
                        session.termination_requested_at or now
                    ),
                )
                self._write_session_locked(updated)
                self._sessions[session_id] = updated
                return updated

    def assert_tool_call_allowed(
        self,
        session_ids: tuple[str, ...],
        *,
        termination_cleanup: bool = False,
    ) -> None:
        """Reject tool work when any referenced session requested termination."""
        if termination_cleanup:
            for session_id in dict.fromkeys(session_ids):
                with self._lock:
                    self._reset_for_current_root_locked()
                    with self._state_store.transaction(
                        self._transaction_path(session_id)
                    ):
                        self._require_session_locked(
                            session_id, allow_expired=True
                        )
            return
        sessions = [
            self.require_session(session_id)
            for session_id in dict.fromkeys(session_ids)
        ]
        for session in sessions:
            if session.termination_requested_at is not None:
                raise SessionTerminationRequestedError(session.session_id)
        for session in sessions:
            self.touch_session(session.session_id)

    def change_session_workdir(
        self, session_id: str, workdir: str | Path
    ) -> AgentSession:
        """Update a local session workdir and clear its durable snapshots."""
        resolved_workdir = resolve_path(workdir, must_exist=True)
        if not resolved_workdir.is_dir():
            raise NotADirectoryError(str(resolved_workdir))
        with self._lock:
            self._reset_for_current_root_locked()
            with self._state_store.transaction(
                self._transaction_path(session_id)
            ):
                session = self._require_session_locked(session_id)
                if session.target != "local":
                    raise ValueError(
                        "remote session cwd changes are not available"
                    )
                updated = replace(
                    session,
                    workdir=str(resolved_workdir),
                    updated_at=time.time(),
                )
                self._write_session_locked(updated)
                self._sessions[session_id] = updated
                self._snapshots = {
                    key: value
                    for key, value in self._snapshots.items()
                    if key[0] != session_id
                }
                self._state_store.remove(self._snapshots_path(session_id))
                return updated

    def update_remote_session_workdir(
        self, session_id: str, workdir: str
    ) -> AgentSession:
        """Cache a worker-validated remote workdir and clear durable snapshots."""
        if not workdir:
            raise ValueError("remote workdir must not be empty")
        with self._lock:
            self._reset_for_current_root_locked()
            with self._state_store.transaction(
                self._transaction_path(session_id)
            ):
                session = self._require_session_locked(session_id)
                if session.target != "remote":
                    raise ValueError("session is not remote")
                updated = replace(
                    session,
                    workdir=workdir,
                    updated_at=time.time(),
                )
                self._write_session_locked(updated)
                self._sessions[session_id] = updated
                self._snapshots = {
                    key: value
                    for key, value in self._snapshots.items()
                    if key[0] != session_id
                }
                self._state_store.remove(self._snapshots_path(session_id))
                return updated

    def end_session(self, session_id: str) -> AgentSession:
        """Remove one durable session and all state owned by it."""
        with self._lock:
            self._reset_for_current_root_locked()
            registry = self._state_store.layout.sessions_dir / ".registry"
            with (
                self._state_store.transaction(registry),
                self._state_store.transaction(
                    self._transaction_path(session_id)
                ),
            ):
                session = self._require_session_locked(
                    session_id, allow_expired=True
                )
                self._remove_session_state_locked(session_id)
                return session

    def list_sessions(self) -> list[AgentSession]:
        """Return all durable sessions ordered by most recent activity."""
        with self._lock:
            self._reset_for_current_root_locked()
            registry = self._state_store.layout.sessions_dir / ".registry"
            with self._state_store.transaction(registry):
                return self._prune_sessions_locked(time.time())

    def record_file_snapshot(
        self,
        *,
        session_id: str,
        path: str,
        file_sha256: str,
        total_lines: int,
        seen_ranges: tuple[tuple[int, int], ...],
    ) -> SnapshotRecord:
        """Durably record a read/search-visible file snapshot."""
        with self._lock:
            self._reset_for_current_root_locked()
            with self._state_store.transaction(
                self._transaction_path(session_id)
            ):
                self._require_session_locked(session_id)
                self._load_snapshots_locked(session_id)
                next_sequence = 1 + max(
                    (
                        snapshot.sequence
                        for (owner, _), snapshot in self._snapshots.items()
                        if owner == session_id
                    ),
                    default=0,
                )
                record = SnapshotRecord(
                    session_id=session_id,
                    snapshot_id=_new_snapshot_id(),
                    path=path,
                    file_sha256=file_sha256,
                    total_lines=total_lines,
                    seen_ranges=seen_ranges,
                    created_at=time.time(),
                    sequence=next_sequence,
                )
                maximum_bytes = int(get_settings().max_session_snapshot_bytes)
                if (
                    self._encoded_snapshot_payload_bytes([record])
                    > maximum_bytes
                ):
                    raise ValueError(
                        "snapshot metadata exceeds max_session_snapshot_bytes"
                    )
                self._snapshots[(session_id, record.snapshot_id)] = record
                self._prune_snapshots_locked(session_id)
                self._write_snapshots_locked(session_id)
                return record

    def get_snapshot(
        self, session_id: str, snapshot_id: str
    ) -> SnapshotRecord | None:
        """Return a durable snapshot for a session, if it still exists."""
        with self._lock:
            self._reset_for_current_root_locked()
            with self._state_store.transaction(
                self._transaction_path(session_id)
            ):
                self._require_session_locked(session_id)
                self._load_snapshots_locked(session_id)
                return self._snapshots.get((session_id, snapshot_id))

    def clear(self) -> None:
        """Clear all durable and in-process session state. Intended for tests."""
        with self._lock:
            self._reset_for_current_root_locked()
            self._state_store.remove(
                self._state_store.layout.sessions_dir, recursive=True
            )
            self._sessions.clear()
            self._snapshots.clear()


def resolve_session_path(
    session: AgentSession,
    path: str | Path,
    *,
    must_exist: bool = False,
    allow_missing_parent: bool = True,
    follow_final_symlink: bool = True,
) -> Path:
    """Resolve a path relative to a local session workdir and enforce containment."""
    if session.target != "local":
        raise ValueError("remote sessions are not dispatchable locally yet")
    workdir = Path(session.workdir).resolve()
    raw = Path(path)
    candidate = raw if raw.is_absolute() else workdir / raw
    resolved = resolve_path(
        candidate,
        must_exist=must_exist,
        allow_missing_parent=allow_missing_parent,
        follow_final_symlink=follow_final_symlink,
    )
    boundary = resolved if follow_final_symlink else resolved.parent
    try:
        boundary.relative_to(workdir)
    except ValueError as exc:
        raise ValueError(f"Path escapes session workdir: {path}") from exc
    return resolved


def file_sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file without loading it all at once."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tool_input_session_ids(value: Any) -> tuple[str, ...]:
    """Extract session ids only from semantic tool-argument positions."""
    found: list[str] = []
    seen: set[int] = set()
    session_names = (
        "session_id",
        "src_session_id",
        "dst_session_id",
        "source_session_id",
        "destination_session_id",
    )
    argument_envelopes = ("kwargs", "keyword_args")

    def visit(candidate: Any) -> None:
        if not isinstance(candidate, Mapping):
            return
        identity = id(candidate)
        if identity in seen:
            return
        seen.add(identity)
        for name in session_names:
            child = candidate.get(name)
            if isinstance(child, str) and child:
                found.append(child)
        for name in argument_envelopes:
            visit(candidate.get(name))

    visit(value)
    return tuple(dict.fromkeys(found))


def enforce_tool_session_control(
    value: Any, *, termination_cleanup: bool = False
) -> None:
    """Apply persisted immediate-stop policy to one model tool invocation."""
    session_ids = tool_input_session_ids(value)
    if session_ids:
        get_tool_session_store().assert_tool_call_allowed(
            session_ids, termination_cleanup=termination_cleanup
        )


_STORE = ToolSessionStore()


def get_tool_session_store() -> ToolSessionStore:
    """Return the process-wide durable session and grounding store."""
    return _STORE
