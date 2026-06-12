"""Shared abstractions for tool definition registries."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..config.settings import Settings

type ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]

type HttpMethod = Literal["GET", "POST"]


@dataclass(frozen=True)
class HttpToolRoute:
    """HTTP endpoint metadata for a tool exposed through the REST adapter."""

    method: HttpMethod
    """HTTP verb accepted by the route."""
    path: str
    """Absolute REST path registered on the FastAPI app."""
    tool_name: str
    """Canonical local tool name dispatched by this route."""


@dataclass(frozen=True)
class McpToolContext:
    """Shared MCP registration context prepared by the app assembler."""

    settings: Settings
    """Runtime settings object shared by all tool registries."""
    read_only_tool: ToolAnnotations
    """MCP annotation applied to read-only tools."""
    connector_meta: dict[str, Any]
    """Client-facing metadata advertised for connector-style read-only MCP tools."""
    protected_meta: dict[str, Any]
    """Client-facing metadata advertised for protected MCP tools."""
    ok: Callable[[Any, str], dict[str, Any]]
    """Helper that wraps successful tool responses in the public envelope."""
    handled_error: Callable[[Exception], dict[str, Any]]
    """Helper that converts handled exceptions into public error envelopes."""


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


class StaticHttpToolRegistry(ToolRegistry):
    """Base class for registries with static REST routes and handlers."""

    routes: ClassVar[Iterable[HttpToolRoute]] = ()
    """Static REST routes provided by this registry."""
    handlers: ClassVar[Mapping[str, ToolHandler]] = {}
    """Static HTTP invocation handlers provided by this registry."""

    def http_routes(self) -> Iterable[HttpToolRoute]:
        """Return static REST routes provided by this registry."""
        return self.routes

    def http_handlers(self) -> Mapping[str, ToolHandler]:
        """Return static HTTP invocation handlers provided by this registry."""
        return self.handlers
