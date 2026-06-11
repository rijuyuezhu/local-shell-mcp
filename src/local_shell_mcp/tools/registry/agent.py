"""Agent bridge MCP tool registry."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..base import McpToolContext, ToolRegistry
from .local import register_agent_bridge_mcp


class AgentBridgeToolRegistry(ToolRegistry):
    """Register agent bridge tools."""

    name = "agent_bridge"

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_agent_bridge_mcp(mcp, context)
