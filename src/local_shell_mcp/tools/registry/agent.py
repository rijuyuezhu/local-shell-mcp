"""Agent bridge MCP tool registry."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...agent_bridge.mcp import AgentMcpClientManager
from ...agent_bridge.models import AgentCapabilityRegistry
from ...agent_bridge.service import (
    activate_agent_skill_payload,
    agent_config_status_payload,
    build_agent_registry_from_settings,
    call_agent_mcp_tool_payload,
    list_agent_mcp_servers_payload,
    list_agent_mcp_tools_payload,
    list_agent_skills_payload,
)
from ...agent_bridge.tools import register_agent_bridge_dynamic_tools
from ...config.settings import Settings
from ..contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry
from ..responses import handled_error, ok_response


def _agent_registry() -> AgentCapabilityRegistry:
    return build_agent_registry_from_settings(
        client_manager_factory=AgentMcpClientManager
    )


def _agent_bridge_enabled(settings: Settings) -> bool:
    return settings.agent_bridge_enabled


class AgentBridgeToolRegistry(DeclarativeToolRegistry):
    """Register agent bridge tools."""

    name = "agent_bridge"

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        if not context.settings.agent_bridge_enabled:
            return
        super().register_mcp(mcp, context)
        register_agent_bridge_dynamic_mcp(mcp, context)


local_tool = AgentBridgeToolRegistry.get_tool_decorator()


@local_tool(
    http_method="GET",
    http_path="/tools/agent_config_status",
    enabled=_agent_bridge_enabled,
)
async def agent_config_status() -> dict[str, Any]:
    """Return agent bridge configuration status."""
    return agent_config_status_payload(_agent_registry())


@local_tool(
    http_method="GET",
    http_path="/tools/list_agent_skills",
    enabled=_agent_bridge_enabled,
)
async def list_agent_skills() -> dict[str, Any]:
    """List agent skills discovered from config."""
    return list_agent_skills_payload(_agent_registry())


@local_tool(
    http_method="POST",
    http_path="/tools/activate_agent_skill",
    enabled=_agent_bridge_enabled,
)
async def activate_agent_skill(name: str) -> dict[str, Any]:
    """Load an agent skill's instructions."""
    return activate_agent_skill_payload(_agent_registry(), name)


@local_tool(
    http_method="GET",
    http_path="/tools/list_agent_mcp_servers",
    enabled=_agent_bridge_enabled,
)
async def list_agent_mcp_servers() -> dict[str, Any]:
    """List configured agent MCP servers."""
    return list_agent_mcp_servers_payload(_agent_registry())


@local_tool(
    http_method="POST",
    http_path="/tools/list_agent_mcp_tools",
    enabled=_agent_bridge_enabled,
)
async def list_agent_mcp_tools(server: str | None = None) -> dict[str, Any]:
    """List tools exposed by configured agent MCP servers."""
    return list_agent_mcp_tools_payload(_agent_registry(), server)


@local_tool(
    http_method="POST",
    http_path="/tools/call_agent_mcp_tool",
    enabled=_agent_bridge_enabled,
)
async def call_agent_mcp_tool(
    server: str, tool: str, args: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Call a tool on a configured agent MCP server."""
    return await call_agent_mcp_tool_payload(
        _agent_registry(), server, tool, args or {}
    )


def register_agent_bridge_dynamic_mcp(
    mcp: FastMCP, context: McpToolContext
) -> None:
    """Register dynamic MCP tools for this tool group."""
    settings = context.settings
    protected_meta = context.protected_meta
    registry = build_agent_registry_from_settings(
        settings, AgentMcpClientManager
    )
    register_agent_bridge_dynamic_tools(
        mcp,
        registry,
        protected_meta,
        ok_response,
        handled_error,
        settings.agent_mcp_probe_timeout_s,
        None if settings.agent_dynamic_mcp_tools else False,
        None if settings.agent_dynamic_skill_tools else False,
    )
