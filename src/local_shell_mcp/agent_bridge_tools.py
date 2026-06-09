from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any

from .agent_bridge import AgentCapabilityRegistry, activate_skill

OkFn = Callable[..., dict[str, Any]]
HandledErrorFn = Callable[[Exception], dict[str, Any]]


def _tool_value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _tool_row(server: str, tool: Any) -> dict[str, Any]:
    if is_dataclass(tool) and not isinstance(tool, type):
        data = asdict(tool)
    elif hasattr(tool, "model_dump"):
        data = tool.model_dump(mode="json")
    elif isinstance(tool, dict):
        data = tool
    else:
        data = {}

    input_schema = data.get("input_schema")
    if input_schema is None:
        input_schema = data.get("inputSchema")
    if input_schema is None:
        input_schema = _tool_value(tool, "input_schema")
    if input_schema is None:
        input_schema = _tool_value(tool, "inputSchema", {})

    return {
        "server": server,
        "tool": str(data.get("name") or _tool_value(tool, "name", "")),
        "description": str(data.get("description") or _tool_value(tool, "description", "") or ""),
        "input_schema": input_schema or {},
    }


def register_agent_bridge_tools(
    mcp: Any,
    registry: AgentCapabilityRegistry,
    meta: dict[str, Any],
    ok: OkFn,
    handled_error: HandledErrorFn,
) -> None:
    @mcp.tool(meta=meta)
    async def agent_config_status() -> dict:
        """Return agent bridge configuration status."""
        return ok(registry.config_status())

    @mcp.tool(meta=meta)
    async def list_agent_skills() -> dict:
        """List agent skills discovered from config."""
        return ok(
            {
                "skills": [asdict(skill) for skill in registry.skills.values()],
                "warnings": registry.skill_warnings,
            }
        )

    @mcp.tool(meta=meta)
    async def activate_agent_skill(name: str) -> dict:
        """Load an agent skill's instructions."""
        try:
            skill = registry.skills.get(name)
            if skill is None:
                raise ValueError(f"Unknown agent skill: {name}")
            return ok(activate_skill(registry.config_dir, skill))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=meta)
    async def list_agent_mcp_servers() -> dict:
        """List configured agent MCP servers."""
        return ok(registry.config_status()["mcp_servers"])

    @mcp.tool(meta=meta)
    async def list_agent_mcp_tools(server: str | None = None) -> dict:
        """List tools exposed by configured agent MCP servers."""
        try:
            if server is not None and server not in registry.mcp_servers:
                raise ValueError(f"Unknown agent MCP server: {server}")
            records = (
                [(server, registry.mcp_servers[server])]
                if server is not None
                else registry.mcp_servers.items()
            )
            rows = [
                _tool_row(server_name, tool)
                for server_name, record in records
                for tool in record.tools
            ]
            return ok({"tools": rows})
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=meta)
    async def call_agent_mcp_tool(
        server: str, tool: str, args: dict[str, Any] | None = None
    ) -> dict:
        """Call a tool on a configured agent MCP server."""
        try:
            record = registry.mcp_servers.get(server)
            if record is None:
                raise ValueError(f"Unknown agent MCP server: {server}")
            if not record.config.enabled:
                raise ValueError(f"MCP server {server} is disabled")
            if not record.available:
                raise ValueError(
                    f"MCP server {server} is unavailable: {record.error or 'unknown error'}"
                )
            data = await registry.client_manager.call_tool(server, record.config, tool, args or {})
            return ok(data)
        except Exception as exc:
            return handled_error(exc)
