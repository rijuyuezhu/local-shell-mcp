"""Environment info MCP tool registry."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...config.settings import get_settings, safe_settings_dump
from ...ops.command_ops import effective_tool_limits, run_shell
from ..base import (
    HttpToolRoute,
    McpToolContext,
    StaticHttpToolRegistry,
    ToolHandler,
)
from ..responses import handled_error, ok_response


async def _environment_info(args: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    result = await run_shell(
        "uname -a; echo '---'; id; echo '---'; pwd; echo '---'; python3 --version; git --version",
        cwd=".",
        timeout_s=10,
    )
    return {
        "settings": safe_settings_dump(settings),
        "effective_tool_limits": effective_tool_limits(),
        "probe": result.model_dump(),
    }


ENVIRONMENT_HTTP_ROUTES = (
    HttpToolRoute("GET", "/tools/environment_info", "environment_info"),
)

ENVIRONMENT_HTTP_HANDLERS: dict[str, ToolHandler] = {
    "environment_info": _environment_info,
}


class EnvironmentToolRegistry(StaticHttpToolRegistry):
    """Register environment/probe tools."""

    name = "environment"

    routes = ENVIRONMENT_HTTP_ROUTES
    handlers = ENVIRONMENT_HTTP_HANDLERS

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_environment_mcp(mcp, context)


def register_environment_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register MCP tools for this tool group."""
    protected_meta = context.protected_meta

    @mcp.tool(meta=protected_meta)
    async def environment_info() -> dict:
        """Return the active workspace, server settings, auth/policy state, and a small environment probe. Use this before planning tool-heavy work when you need to know the workspace root, timeout/output limits, network policy, or basic runtime versions. This is read-only and intended for orientation, not for executing arbitrary commands."""
        try:
            return ok_response(await _environment_info({}))
        except Exception as exc:
            return handled_error(exc)
