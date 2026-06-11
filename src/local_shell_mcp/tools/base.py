"""Shared abstractions for tool definition registries."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import FastMCP

ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class HttpToolRoute:
    """HTTP endpoint metadata for a tool exposed through the REST adapter."""

    method: str
    path: str
    tool_name: str


class ToolRegistry:
    """Base class for modules that describe MCP and HTTP tool exposure."""

    name: str = ""
    owns_mcp: bool = False

    def http_routes(self) -> Iterable[HttpToolRoute]:
        """Return REST routes provided by this registry."""
        return ()

    def http_handlers(self) -> Mapping[str, ToolHandler]:
        """Return canonical tool-name to HTTP invocation handler mappings."""
        return {}

    def build_mcp(self) -> FastMCP | None:
        """Build a complete FastMCP app when this registry owns MCP assembly."""
        return None
