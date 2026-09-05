"""Typed outputs for session-bound audit queries."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class AuditTailOutput(BaseModel):
    """Bounded logical audit query result for one local or remote target."""

    session_id: str
    """Explicit agent session used to select the local or remote audit target."""
    target: Literal["local", "remote"]
    """Audit target selected by the explicit session."""
    machine: str | None = None
    """Configured remote worker name, or None for a local session."""
    entries: list[dict[str, Any]] = Field(default_factory=list)
    """Bounded logical audit entries with references or resolved sanitized values."""
    count: int
    """Number of entries returned in this response."""
    total_matched: int
    """Number of logical entries matching the filters before the limit."""
    failed_matched: int
    """Number of matching logical entries with failed status."""
    entry_id: str | None = None
    """Requested stable logical entry id for detail mode."""
    full_payloads: bool = False
    """Whether retained sanitized payload references were requested for resolution."""
