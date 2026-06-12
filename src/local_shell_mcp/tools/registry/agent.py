"""Agent bridge MCP tool registry."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...agent_bridge.mcp import AgentMcpClientManager
from ...agent_bridge.service import (
    activate_agent_skill_payload,
    agent_config_status_payload,
    build_agent_registry_from_settings,
    call_agent_mcp_tool_payload,
    list_agent_mcp_servers_payload,
    list_agent_mcp_tools_payload,
    list_agent_skills_payload,
)
from ...agent_bridge.tools import register_agent_bridge_tools
from ...config.settings import get_settings
from ..base import HttpToolRoute, McpToolContext, ToolHandler, ToolRegistry
from ..responses import handled_error, ok_response


def _agent_registry():
    return build_agent_registry_from_settings(
        client_manager_factory=AgentMcpClientManager
    )


async def _agent_config_status(args: dict[str, Any]) -> dict[str, Any]:
    return agent_config_status_payload(_agent_registry())


async def _list_agent_skills(args: dict[str, Any]) -> dict[str, Any]:
    return list_agent_skills_payload(_agent_registry())


async def _activate_agent_skill(args: dict[str, Any]) -> dict[str, Any]:
    return activate_agent_skill_payload(_agent_registry(), args["name"])


async def _list_agent_mcp_servers(args: dict[str, Any]) -> dict[str, Any]:
    return list_agent_mcp_servers_payload(_agent_registry())


async def _list_agent_mcp_tools(args: dict[str, Any]) -> dict[str, Any]:
    return list_agent_mcp_tools_payload(_agent_registry(), args.get("server"))


async def _call_agent_mcp_tool(args: dict[str, Any]) -> dict[str, Any]:
    return await call_agent_mcp_tool_payload(
        _agent_registry(),
        args["server"],
        args["tool"],
        args.get("args") or {},
    )


AGENT_BRIDGE_HTTP_ROUTES = (
    HttpToolRoute("GET", "/tools/agent_config_status", "agent_config_status"),
    HttpToolRoute("GET", "/tools/list_agent_skills", "list_agent_skills"),
    HttpToolRoute(
        "POST", "/tools/activate_agent_skill", "activate_agent_skill"
    ),
    HttpToolRoute(
        "GET", "/tools/list_agent_mcp_servers", "list_agent_mcp_servers"
    ),
    HttpToolRoute(
        "POST", "/tools/list_agent_mcp_tools", "list_agent_mcp_tools"
    ),
    HttpToolRoute("POST", "/tools/call_agent_mcp_tool", "call_agent_mcp_tool"),
)

AGENT_BRIDGE_HTTP_HANDLERS: dict[str, ToolHandler] = {
    "agent_config_status": _agent_config_status,
    "list_agent_skills": _list_agent_skills,
    "activate_agent_skill": _activate_agent_skill,
    "list_agent_mcp_servers": _list_agent_mcp_servers,
    "list_agent_mcp_tools": _list_agent_mcp_tools,
    "call_agent_mcp_tool": _call_agent_mcp_tool,
}


class AgentBridgeToolRegistry(ToolRegistry):
    """Register agent bridge tools."""

    name = "agent_bridge"

    def http_routes(self):
        if not get_settings().agent_bridge_enabled:
            return ()
        return AGENT_BRIDGE_HTTP_ROUTES

    def http_handlers(self):
        if not get_settings().agent_bridge_enabled:
            return {}
        return AGENT_BRIDGE_HTTP_HANDLERS

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_agent_bridge_mcp(mcp, context)


def register_agent_bridge_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register MCP tools for this tool group."""
    settings = context.settings
    protected_meta = context.protected_meta
    if settings.agent_bridge_enabled:
        registry = build_agent_registry_from_settings(
            settings, AgentMcpClientManager
        )
        register_agent_bridge_tools(
            mcp,
            registry,
            protected_meta,
            ok_response,
            handled_error,
            settings.agent_mcp_probe_timeout_s,
            None if settings.agent_dynamic_mcp_tools else False,
            None if settings.agent_dynamic_skill_tools else False,
        )
