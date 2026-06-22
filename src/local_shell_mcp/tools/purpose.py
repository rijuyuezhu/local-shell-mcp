"""Shared purpose metadata helper for high-impact tool calls."""

from ..audit import audit


def audit_tool_purpose(
    tool_name: str, purpose: str | None, explanation: str | None
) -> None:
    """Record optional operator-supplied purpose metadata for a tool call."""
    details: dict[str, str] = {}
    if purpose is not None:
        purpose = purpose.strip()
        if len(purpose) > 500:
            raise ValueError("purpose must be <= 500 characters")
        if purpose:
            details["purpose"] = purpose
    if explanation is not None:
        explanation = explanation.strip()
        if len(explanation) > 2000:
            raise ValueError("explanation must be <= 2000 characters")
        if explanation:
            details["explanation"] = explanation
    if details:
        audit("tool_call_purpose", tool=tool_name, **details)
