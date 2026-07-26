"""Stable public facade for audit logging and query operations."""

from typing import Any

from . import core as _core
from .core import (
    audit,
    audit_call_context,
    audit_tool_call_end,
    audit_tool_call_start,
    current_audit_call_id,
    get_audit_entry,
    get_session_audit_entry,
    new_audit_call_id,
    query_audit,
    query_session_audit,
)

__all__ = [
    "audit",
    "audit_call_context",
    "audit_tool_call_end",
    "audit_tool_call_start",
    "current_audit_call_id",
    "get_audit_entry",
    "get_session_audit_entry",
    "new_audit_call_id",
    "query_audit",
    "query_session_audit",
]


def __getattr__(name: str) -> Any:
    """Forward legacy module attributes to the implementation module."""
    return getattr(_core, name)


def __dir__() -> list[str]:
    """Expose facade and implementation attributes for diagnostics."""
    return sorted(set(globals()) | set(dir(_core)))
