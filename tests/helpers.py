from __future__ import annotations

from typing import Any


def mcp_text(response: Any, index: int = 0) -> str:
    """Return text from a FastMCP call_tool response in tests."""
    return str(response[index].text)


def nested_mcp_text(
    response: Any, index: int = 0, nested_index: int = 0
) -> str:
    """Return text from nested FastMCP responses produced by fetch tests."""
    return str(response[index][nested_index].text)
