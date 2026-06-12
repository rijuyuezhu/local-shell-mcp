"""Agent bridge MCP tool registry."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from mcp.server.fastmcp import FastMCP

from ...agent_bridge.mcp import AgentMcpClientManager
from ...agent_bridge.redaction import _redact_text, redact_configured_values
from ...agent_bridge.registry import build_agent_registry
from ...agent_bridge.skills import activate_skill
from ...agent_bridge.tools import (
    _redact_mcp_error_payload,
    _redacted_mcp_call_error,
    _tool_row,
    _tool_value,
    register_agent_bridge_tools,
)
from ...config.settings import get_settings
from ..base import HttpToolRoute, McpToolContext, ToolHandler, ToolRegistry
from ..responses import handled_error, ok_response


def _agent_registry():
    settings = get_settings()
    return build_agent_registry(
        settings.agent_config_dir,
        AgentMcpClientManager(settings.agent_mcp_call_timeout_s),
        settings.agent_mcp_probe_timeout_s,
        None if settings.agent_dynamic_mcp_tools else False,
        None if settings.agent_dynamic_skill_tools else False,
    )


async def _agent_config_status(args: dict[str, Any]) -> dict[str, Any]:
    return _agent_registry().config_status()


async def _list_agent_skills(args: dict[str, Any]) -> dict[str, Any]:
    registry = _agent_registry()
    return {
        "skills": [asdict(skill) for skill in registry.skills.values()],
        "warnings": registry.skill_warnings,
    }


async def _activate_agent_skill(args: dict[str, Any]) -> dict[str, Any]:
    registry = _agent_registry()
    skill = registry.skills.get(args["name"])
    if skill is None:
        raise ValueError(f"Unknown agent skill: {args['name']}")
    return activate_skill(registry.config_dir, skill)


async def _list_agent_mcp_servers(args: dict[str, Any]) -> list[dict[str, Any]]:
    return _agent_registry().config_status()["mcp_servers"]


async def _list_agent_mcp_tools(args: dict[str, Any]) -> dict[str, Any]:
    registry = _agent_registry()
    server = args.get("server")
    if server is not None and server not in registry.mcp_servers:
        raise ValueError(f"Unknown agent MCP server: {server}")
    records = (
        [(server, registry.mcp_servers[server])]
        if server is not None
        else registry.mcp_servers.items()
    )
    dynamic_names = {
        (record.server_name, record.tool_name): dynamic_name
        for dynamic_name, record in registry.dynamic_mcp_tool_map.items()
    }
    rows = [
        _tool_row(
            server_name,
            tool,
            record.config.env,
            record.config.headers,
            dynamic_names.get(
                (server_name, str(_tool_value(tool, "name", "")))
            ),
        )
        for server_name, record in records
        for tool in record.tools
    ]
    return {"tools": rows}


async def _call_agent_mcp_tool(args: dict[str, Any]) -> dict[str, Any]:
    registry = _agent_registry()
    server = args["server"]
    tool = args["tool"]
    tool_args = args.get("args") or {}
    record = registry.mcp_servers.get(server)
    if record is None:
        raise ValueError(f"Unknown agent MCP server: {server}")
    if not record.config.enabled:
        raise ValueError(f"MCP server {server} is disabled")
    if not record.available:
        error = (
            _redact_text(
                redact_configured_values(
                    record.error,
                    record.config.env,
                    record.config.headers,
                )
            )
            if record.error
            else "unknown error"
        )
        raise ValueError(f"MCP server {server} is unavailable: {error}")
    try:
        data = await registry.client_manager.call_tool(
            server, record.config, tool, tool_args
        )
    except Exception as exc:
        raise _redacted_mcp_call_error(
            exc, record.config.env, record.config.headers
        ) from None
    return _redact_mcp_error_payload(
        data, record.config.env, record.config.headers
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
            protected_meta,
            ok_response,
            handled_error,
            settings.agent_mcp_probe_timeout_s,
            None if settings.agent_dynamic_mcp_tools else False,
            None if settings.agent_dynamic_skill_tools else False,
        )
