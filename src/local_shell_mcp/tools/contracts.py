"""Tool registry contracts and transport-facing metadata types."""

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

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
    """Local tool name dispatched by this route."""


@dataclass(frozen=True)
class McpToolContext:
    """Shared MCP registration context prepared by the app assembler."""

    settings: Settings
    """Runtime settings object shared by all tool registries."""
    read_only_tool: ToolAnnotations
    """MCP annotation applied to read-only tools."""
    connector_compatible_security_meta: dict[str, Any]
    """Client-facing securitySchemes metadata for connector-compatible search/fetch tools."""
    oauth_security_meta: dict[str, Any]
    """Client-facing securitySchemes metadata for OAuth-protected MCP tools."""


class ToolRegistry:
    """Base class that registers MCP and HTTP tool routes for a group of related tools. Derived classes are automatically registered if they are placed in the `local_shell_mcp.tools.registry.*` module"""

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
