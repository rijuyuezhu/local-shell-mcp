"""Local tool handler catalog and dispatch helpers."""

from collections.abc import Mapping
from typing import Any

from .catalog import ToolCatalog, build_tool_catalog
from .contracts import ToolHandler


class UnknownLocalToolError(LookupError):
    """Raised when a local tool name has no registered invocation handler."""


def local_tool_handlers(
    catalog: ToolCatalog | None = None,
) -> Mapping[str, ToolHandler]:
    """Return local handlers from one explicit catalog composition."""
    resolved = catalog or build_tool_catalog()
    return resolved.local_handlers()


async def call_local_tool(
    tool_name: str,
    args: dict[str, Any] | None = None,
    *,
    catalog: ToolCatalog | None = None,
) -> Any:
    """Invoke a local tool by canonical MCP tool name."""
    try:
        handler = local_tool_handlers(catalog)[tool_name]
    except KeyError as exc:
        raise UnknownLocalToolError(f"Unknown local tool: {tool_name}") from exc
    return await handler(args or {})
