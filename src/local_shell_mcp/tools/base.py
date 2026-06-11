"""Shared abstractions for tool definition registries."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class HttpToolRoute:
    """HTTP endpoint metadata for a tool exposed through the REST adapter."""

    method: str
    path: str
    tool_name: str


@dataclass(frozen=True)
class McpToolContext:
    """Shared MCP registration context prepared by the app assembler."""

    settings: Any
    read_only_tool: ToolAnnotations
    read_only_meta: dict[str, Any]
    oauth_meta: dict[str, Any]
    ok: Callable[[Any, str], dict]
    handled_error: Callable[[Exception], dict]


class ToolRegistry:
    """Base class for modules that describe MCP and HTTP tool exposure."""

    name: str = ""

    def http_routes(self) -> Iterable[HttpToolRoute]:
        """Return REST routes provided by this registry."""
        return ()

    def http_handlers(self) -> Mapping[str, ToolHandler]:
        """Return canonical tool-name to HTTP invocation handler mappings."""
        return {}

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        """Register MCP tools for this registry onto the provided app."""
        return None
