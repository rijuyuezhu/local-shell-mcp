"""In-process state for explicit agent/workspace sessions and grounding snapshots."""

import secrets
import string
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from ..ops.utils.path import resolve_path

SESSION_ID_ALPHABET = string.ascii_letters + string.digits
SESSION_ID_LENGTH = 8
SessionTarget = Literal["local", "remote"]


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


def generate_session_id() -> str:
    """Return one opaque 8-character alphanumeric agent session id."""
    return "".join(
        secrets.choice(SESSION_ID_ALPHABET) for _ in range(SESSION_ID_LENGTH)
    )


def _new_snapshot_id() -> str:
    """Return an opaque snapshot id for one displayed file view."""
    return secrets.token_hex(6)


class UnknownAgentSessionError(KeyError):
    """Raised when a tool call references a missing agent session."""


class ToolSessionStore:
    """Track explicit agent sessions plus file snapshots shown in them."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, AgentSession] = {}
        self._snapshots: dict[tuple[str, str], SnapshotRecord] = {}

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
        """Create and store one explicit agent workspace session."""
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
            for _ in range(16):
                session_id = generate_session_id()
                if session_id not in self._sessions:
                    break
            else:
                raise RuntimeError("failed to allocate a unique session_id")
            now = time.time()
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
            )
            self._sessions[session_id] = session
            return session

    def require_session(self, session_id: str) -> AgentSession:
        """Return an existing explicit agent session or raise a clear error."""
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise UnknownAgentSessionError(
                f"unknown session_id {session_id!r}; call session_start first"
            )
        return session

    def touch_session(self, session_id: str) -> AgentSession:
        """Refresh a session's updated timestamp and return the new record."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise UnknownAgentSessionError(
                    f"unknown session_id {session_id!r}; call session_start first"
                )
            updated = replace(session, updated_at=time.time())
            self._sessions[session_id] = updated
            return updated

    def end_session(self, session_id: str) -> AgentSession:
        """Remove one session and all snapshots owned by it."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session is None:
                raise UnknownAgentSessionError(
                    f"unknown session_id {session_id!r}; call session_start first"
                )
            self._snapshots = {
                key: value
                for key, value in self._snapshots.items()
                if key[0] != session_id
            }
            return session

    def record_file_snapshot(
        self,
        *,
        session_id: str,
        path: str,
        file_sha256: str,
        total_lines: int,
        seen_ranges: tuple[tuple[int, int], ...],
    ) -> SnapshotRecord:
        """Record a read/search-visible file snapshot and return its handle."""
        self.require_session(session_id)
        record = SnapshotRecord(
            session_id=session_id,
            snapshot_id=_new_snapshot_id(),
            path=path,
            file_sha256=file_sha256,
            total_lines=total_lines,
            seen_ranges=seen_ranges,
            created_at=time.time(),
        )
        with self._lock:
            self._snapshots[(record.session_id, record.snapshot_id)] = record
        return record

    def get_snapshot(
        self, session_id: str, snapshot_id: str
    ) -> SnapshotRecord | None:
        """Return a recorded snapshot for a session, if it still exists."""
        self.require_session(session_id)
        with self._lock:
            return self._snapshots.get((session_id, snapshot_id))

    def clear(self) -> None:
        """Clear all in-process session state. Intended for tests."""
        with self._lock:
            self._sessions.clear()
            self._snapshots.clear()


def resolve_session_path(
    session: AgentSession,
    path: str | Path,
    *,
    must_exist: bool = False,
    allow_missing_parent: bool = True,
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
    )
    try:
        resolved.relative_to(workdir)
    except ValueError as exc:
        raise ValueError(f"Path escapes session workdir: {path}") from exc
    return resolved


def file_sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file without loading it all at once."""
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_STORE = ToolSessionStore()


def get_tool_session_store() -> ToolSessionStore:
    """Return the process-local session and grounding store."""
    return _STORE
