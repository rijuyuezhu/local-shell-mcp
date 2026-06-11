"""Agent bridge MCP tool registry."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ...agent_bridge import build_agent_registry
from ...agent_bridge.mcp import AgentMcpClientManager
from ...agent_bridge.tools import register_agent_bridge_tools
from ..base import McpToolContext, ToolRegistry
from .common import handled_error, ok_response


class AgentBridgeToolRegistry(ToolRegistry):
    """Register agent bridge tools."""

    name = "agent_bridge"

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_agent_bridge_mcp(mcp, context)


def register_agent_bridge_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register MCP tools for this tool group."""
    settings = context.settings
    oauth_meta = context.oauth_meta
    if settings.agent_bridge_enabled:
        registry = build_agent_registry(
            settings.agent_config_dir,
            AgentMcpClientManager(settings.agent_mcp_call_timeout_s),
            settings.agent_mcp_probe_timeout_s,
            None if settings.agent_dynamic_mcp_tools else False,
            None if settings.agent_dynamic_skill_tools else False,
        )
        register_agent_bridge_tools(
            mcp,
            registry,
            oauth_meta,
            ok_response,
            handled_error,
            settings.agent_mcp_probe_timeout_s,
            None if settings.agent_dynamic_mcp_tools else False,
            None if settings.agent_dynamic_skill_tools else False,
        )
