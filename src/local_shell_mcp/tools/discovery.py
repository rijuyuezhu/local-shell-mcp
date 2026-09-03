"""Compatibility access to the explicit built-in tool catalog."""

from .catalog import build_tool_catalog
from .contracts import ToolRegistry


def discover_tool_registries() -> tuple[ToolRegistry, ...]:
    """Return fresh built-in registries from the explicit catalog definition."""
    return build_tool_catalog().registries
