from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any

from .agent_bridge import AgentCapabilityRegistry, _redact_text, activate_skill

OkFn = Callable[..., dict[str, Any]]
HandledErrorFn = Callable[[Exception], dict[str, Any]]


def _tool_value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _tool_row(
    server: str, tool: Any, dynamic_tool_name: str | None = None
) -> dict[str, Any]:
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

    row = {
        "server": server,
        "tool": str(data.get("name") or _tool_value(tool, "name", "")),
        "description": str(data.get("description") or _tool_value(tool, "description", "") or ""),
        "input_schema": input_schema or {},
    }
    if dynamic_tool_name is not None:
        row["dynamic_tool_name"] = dynamic_tool_name
    return row


def _redacted_mcp_call_error(exc: Exception) -> ValueError:
    return ValueError(f"Agent MCP tool call failed: {_redact_text(str(exc))}")


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
            dynamic_names = {
                (record.server_name, record.tool_name): dynamic_name
                for dynamic_name, record in registry.dynamic_mcp_tool_map.items()
            }
            rows = [
                _tool_row(
                    server_name,
                    tool,
                    dynamic_names.get(
                        (server_name, str(_tool_value(tool, "name", "")))
                    ),
                )
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
                error = _redact_text(record.error) if record.error else "unknown error"
                raise ValueError(f"MCP server {server} is unavailable: {error}")
            try:
                data = await registry.client_manager.call_tool(
                    server, record.config, tool, args or {}
                )
            except Exception as exc:
                raise _redacted_mcp_call_error(exc) from None
            return ok(data)
        except Exception as exc:
            return handled_error(exc)

    def make_skill_handler(skill_name: str):  # noqa: ANN202
        async def handler() -> dict:
            try:
                skill = registry.skills[skill_name]
                return ok(activate_skill(registry.config_dir, skill))
            except Exception as exc:
                return handled_error(exc)

        return handler

    for dynamic_name, record in registry.dynamic_skill_tool_map.items():
        skill = registry.skills[record.skill_name]
        description = f"[agent skill] Activate {record.skill_name}: {skill.description}"
        mcp.tool(name=dynamic_name, description=description, meta=meta)(
            make_skill_handler(record.skill_name)
        )

    def make_mcp_handler(server_name: str, tool_name: str):  # noqa: ANN202
        async def handler(args: dict[str, Any] | None = None) -> dict:
            try:
                record = registry.mcp_servers[server_name]
                try:
                    data = await registry.client_manager.call_tool(
                        server_name, record.config, tool_name, args or {}
                    )
                except Exception as exc:
                    raise _redacted_mcp_call_error(exc) from None
                return ok(data)
            except Exception as exc:
                return handled_error(exc)

        return handler

    for dynamic_name, record in registry.dynamic_mcp_tool_map.items():
        server_record = registry.mcp_servers[record.server_name]
        tool = next(
            candidate
            for candidate in server_record.tools
            if str(_tool_value(candidate, "name", "")) == record.tool_name
        )
        tool_description = str(_tool_value(tool, "description", "") or record.tool_name)
        description = f"[agent mcp: {record.server_name}] {tool_description}"
        mcp.tool(name=dynamic_name, description=description, meta=meta)(
            make_mcp_handler(record.server_name, record.tool_name)
        )
