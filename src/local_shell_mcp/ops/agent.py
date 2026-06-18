"""Agent bridge operation helpers used by the agent tool registry."""

from ..agent_bridge.mcp import AgentMcpClientManager
from ..agent_bridge.models import AgentCapabilityRegistry
from ..agent_bridge.service import (
    activate_agent_skill_payload,
    agent_config_status_payload,
    build_agent_registry_from_settings,
    call_agent_mcp_tool_payload,
    list_agent_mcp_servers_payload,
    list_agent_mcp_tools_payload,
    list_agent_skills_payload,
)
from ..schemas.result_models.agent import (
    ActivateAgentSkillOutput,
    AgentConfigStatusOutput,
    CallAgentMcpToolOutput,
    ListAgentMcpServersOutput,
    ListAgentMcpToolsOutput,
    ListAgentSkillsOutput,
)


def agent_registry() -> AgentCapabilityRegistry:
    """Build the current agent bridge registry from settings."""
    return build_agent_registry_from_settings(
        client_manager_factory=AgentMcpClientManager
    )


def _registry_or_default(
    registry: AgentCapabilityRegistry | None,
) -> AgentCapabilityRegistry:
    return registry if registry is not None else agent_registry()


def agent_config_status_execute(
    registry: AgentCapabilityRegistry | None = None,
) -> AgentConfigStatusOutput:
    """Return current agent bridge configuration status."""
    return agent_config_status_payload(_registry_or_default(registry))


def list_agent_skills_execute(
    registry: AgentCapabilityRegistry | None = None,
) -> ListAgentSkillsOutput:
    """List discovered agent skills."""
    return list_agent_skills_payload(_registry_or_default(registry))


def activate_agent_skill_execute(
    name: str, registry: AgentCapabilityRegistry | None = None
) -> ActivateAgentSkillOutput:
    """Load one discovered agent skill by exact name."""
    return activate_agent_skill_payload(_registry_or_default(registry), name)


def list_agent_mcp_servers_execute(
    registry: AgentCapabilityRegistry | None = None,
) -> ListAgentMcpServersOutput:
    """List configured agent MCP servers."""
    return list_agent_mcp_servers_payload(_registry_or_default(registry))


def list_agent_mcp_tools_execute(
    server: str | None = None,
    registry: AgentCapabilityRegistry | None = None,
) -> ListAgentMcpToolsOutput:
    """List tools exposed by configured agent MCP servers."""
    return list_agent_mcp_tools_payload(_registry_or_default(registry), server)


async def call_agent_mcp_tool_execute(
    server: str,
    tool: str,
    args: dict | None = None,
    registry: AgentCapabilityRegistry | None = None,
) -> CallAgentMcpToolOutput:
    """Call one tool on a configured agent MCP server."""
    return await call_agent_mcp_tool_payload(
        _registry_or_default(registry), server, tool, args or {}
    )
