"""Environment info MCP tool registry."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ...config.settings import safe_settings_dump
from ...ops.shell_ops import run_shell
from ..base import McpToolContext, ToolRegistry
from .common import handled_error, ok_response


class EnvironmentToolRegistry(ToolRegistry):
    """Register environment/probe tools."""

    name = "environment"

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_environment_mcp(mcp, context)


def register_environment_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register MCP tools for this tool group."""
    settings = context.settings
    protected_meta = context.protected_meta

    @mcp.tool(meta=protected_meta)
    async def environment_info() -> dict:
        """Return workspace, auth, policy, and basic environment information."""
        try:
            result = await run_shell(
                "uname -a; echo '---'; id; echo '---'; pwd; echo '---'; python3 --version; git --version",
                cwd=".",
                timeout_s=10,
            )
            return ok_response(
                {
                    "settings": safe_settings_dump(settings),
                    "probe": result.model_dump(),
                }
            )
        except Exception as exc:
            return handled_error(exc)
