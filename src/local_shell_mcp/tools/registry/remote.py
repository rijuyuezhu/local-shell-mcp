"""Remote worker MCP tool registry."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..base import McpToolContext, ToolRegistry
from .local import register_remote_mcp


class RemoteToolRegistry(ToolRegistry):
    """Register remote-worker proxy tools."""

    name = "remote"

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_remote_mcp(mcp, context)
