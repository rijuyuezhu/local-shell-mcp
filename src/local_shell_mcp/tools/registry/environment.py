"""Environment info MCP tool registry."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..base import McpToolContext, ToolRegistry
from .local import register_environment_mcp


class EnvironmentToolRegistry(ToolRegistry):
    """Register environment/probe tools."""

    name = "environment"

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_environment_mcp(mcp, context)
