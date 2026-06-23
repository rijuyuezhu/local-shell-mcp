"""In-process grounding state shared by agent-friendly tools.

MCP transports do not currently provide this project with a stable coding-agent
session identifier, but read/search/edit workflows need a small
amount of state: which file snapshot was shown, what hash it had, and which line
ranges were visible to the model.  This store is intentionally tiny and uses a
single default session unless a future tool passes an explicit session id.
"""

import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TOOL_SESSION_ID = "default"
"""Fallback session id used when the client has no explicit session concept."""


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


class ToolSessionStore:
    """Track file snapshots and line ranges shown to an agent session."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshots: dict[tuple[str, str], SnapshotRecord] = {}

    def record_file_snapshot(
        self,
        *,
        session_id: str | None,
        path: str,
        file_sha256: str,
        total_lines: int,
        seen_ranges: tuple[tuple[int, int], ...],
    ) -> SnapshotRecord:
        """Record a read/search-visible file snapshot and return its handle."""
        normalized_session_id = session_id or DEFAULT_TOOL_SESSION_ID
        record = SnapshotRecord(
            session_id=normalized_session_id,
            snapshot_id=secrets.token_hex(6),
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
        self, session_id: str | None, snapshot_id: str
    ) -> SnapshotRecord | None:
        """Return a recorded snapshot for a session, if it still exists."""
        normalized_session_id = session_id or DEFAULT_TOOL_SESSION_ID
        with self._lock:
            return self._snapshots.get((normalized_session_id, snapshot_id))

    def clear(self) -> None:
        """Clear all in-process session state. Intended for tests."""
        with self._lock:
            self._snapshots.clear()


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
    """Return the process-local grounding store."""
    return _STORE
