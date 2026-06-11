"""Workspace connector MCP tool registry."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..base import McpToolContext, ToolRegistry
from .local import register_workspace_connector_mcp


class WorkspaceConnectorToolRegistry(ToolRegistry):
    """Register ChatGPT connector-compatible workspace tools."""

    name = "workspace_connector"

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_workspace_connector_mcp(mcp, context)
