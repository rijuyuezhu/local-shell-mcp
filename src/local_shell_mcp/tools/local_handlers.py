"""Local tool handler registry and dispatch helpers."""

from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from .contracts import ToolHandler
from .discovery import discover_tool_registries


class UnknownLocalToolError(LookupError):
    """Raised when a local tool name has no registered invocation handler."""


@lru_cache(maxsize=1)
def local_tool_handlers() -> Mapping[str, ToolHandler]:
    """Collect canonical local invocation handlers from discovered registries."""
    handlers: dict[str, ToolHandler] = {}
    for registry in discover_tool_registries():
        for tool_name, handler in registry.http_handlers().items():
            if tool_name in handlers:
                raise ValueError(f"Duplicate local tool handler: {tool_name}")
            handlers[tool_name] = handler
    return handlers


async def call_local_tool(
    tool_name: str,
    args: dict[str, Any] | None = None,
) -> Any:
    """Invoke a local tool by canonical MCP tool name."""
    try:
        handler = local_tool_handlers()[tool_name]
    except KeyError as exc:
        raise UnknownLocalToolError(f"Unknown local tool: {tool_name}") from exc
    return await handler(args or {})
