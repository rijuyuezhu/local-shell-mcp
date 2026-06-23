"""Shared purpose metadata helper for high-impact tool calls."""

from ..audit import audit


def audit_tool_purpose(tool_name: str, purpose: str | None) -> None:
    """Record optional operator-supplied purpose metadata for a tool call."""
    details: dict[str, str] = {}
    if purpose is not None:
        purpose = purpose.strip()
        if len(purpose) > 500:
            raise ValueError("purpose must be <= 500 characters")
        if purpose:
            details["purpose"] = purpose
    if details:
        audit("tool_call_purpose", tool=tool_name, **details)
