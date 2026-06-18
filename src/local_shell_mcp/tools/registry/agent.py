"""Agent bridge MCP tool registry."""

from mcp.server.fastmcp import FastMCP

from ...agent_bridge.mcp import AgentMcpClientManager
from ...agent_bridge.models import AgentCapabilityRegistry
from ...agent_bridge.service import build_agent_registry_from_settings
from ...agent_bridge.tools import register_agent_bridge_dynamic_tools
from ...config.settings import Settings
from ...ops.agent_ops import (
    activate_agent_skill_execute,
    agent_config_status_execute,
    call_agent_mcp_tool_execute,
    list_agent_mcp_servers_execute,
    list_agent_mcp_tools_execute,
    list_agent_skills_execute,
)
from ...schemas.input_models.agent import (
    AgentServerArg,
    AgentServerFilterArg,
    AgentSkillNameArg,
    AgentToolArg,
    AgentToolArgsArg,
)
from ...schemas.result_models.agent import (
    ActivateAgentSkillOutput,
    AgentConfigStatusOutput,
    CallAgentMcpToolOutput,
    ListAgentMcpServersOutput,
    ListAgentMcpToolsOutput,
    ListAgentSkillsOutput,
)
from ..contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry


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
async def agent_config_status() -> AgentConfigStatusOutput:
    """Return agent bridge configuration status, discovered skills, configured MCP servers, and load errors."""
    return agent_config_status_execute(_agent_registry())


@local_tool(
    http_method="GET",
    http_path="/tools/list_agent_skills",
    enabled=_agent_bridge_enabled,
)
async def list_agent_skills() -> ListAgentSkillsOutput:
    """List agent skills discovered from config. Use to find the exact skill name before activate_agent_skill; this only lists available instruction sets and does not load them."""
    return list_agent_skills_execute(_agent_registry())


@local_tool(
    http_method="POST",
    http_path="/tools/activate_agent_skill",
    enabled=_agent_bridge_enabled,
)
async def activate_agent_skill(
    name: AgentSkillNameArg,
) -> ActivateAgentSkillOutput:
    """Load an agent skill's instructions. Parameter name must be the exact skill name returned by list_agent_skills; use before tasks that need that specialized guidance."""
    return activate_agent_skill_execute(name, _agent_registry())


@local_tool(
    http_method="GET",
    http_path="/tools/list_agent_mcp_servers",
    enabled=_agent_bridge_enabled,
)
async def list_agent_mcp_servers() -> ListAgentMcpServersOutput:
    """List configured agent MCP servers. Use to find exact server names and connection status before listing or calling bridged MCP tools."""
    return list_agent_mcp_servers_execute(_agent_registry())


@local_tool(
    http_method="POST",
    http_path="/tools/list_agent_mcp_tools",
    enabled=_agent_bridge_enabled,
)
async def list_agent_mcp_tools(
    server: AgentServerFilterArg = None,
) -> ListAgentMcpToolsOutput:
    """List tools exposed by configured agent MCP servers. Parameter server is optional; omit it for all servers or pass an exact server name before call_agent_mcp_tool."""
    return list_agent_mcp_tools_execute(server, _agent_registry())


@local_tool(
    http_method="POST",
    http_path="/tools/call_agent_mcp_tool",
    enabled=_agent_bridge_enabled,
)
async def call_agent_mcp_tool(
    server: AgentServerArg, tool: AgentToolArg, args: AgentToolArgsArg = None
) -> CallAgentMcpToolOutput:
    """Call a tool on a configured agent MCP server. Parameters: server and tool must match list_agent_mcp_tools; args is a JSON object matching that tool schema, or empty for no-argument tools."""
    return await call_agent_mcp_tool_execute(
        server, tool, args, _agent_registry()
    )


def register_agent_bridge_dynamic_mcp(
    mcp: FastMCP, context: McpToolContext
) -> None:
    """Register dynamic MCP tools for this tool group."""
    settings = context.settings
    oauth_security_meta = context.oauth_security_meta
    registry = build_agent_registry_from_settings(
        settings, AgentMcpClientManager
    )
    register_agent_bridge_dynamic_tools(
        mcp,
        registry,
        oauth_security_meta,
        settings.agent_mcp_probe_timeout_s,
        None if settings.agent_dynamic_mcp_tools else False,
        None if settings.agent_dynamic_skill_tools else False,
    )
