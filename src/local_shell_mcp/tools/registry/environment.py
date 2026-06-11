"""Environment info MCP tool registry."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ...config.settings import safe_settings_dump
from ...ops.shell_ops import run_shell
from ..base import McpToolContext, ToolRegistry
from .common import _handled_error, _ok


class EnvironmentToolRegistry(ToolRegistry):
    """Register environment/probe tools."""

    name = "environment"

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_environment_mcp(mcp, context)


def register_environment_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register MCP tools for this tool group."""
    settings = context.settings
    oauth_meta = context.oauth_meta

    @mcp.tool(meta=oauth_meta)
    async def environment_info() -> dict:
        """Return workspace, auth, policy, and basic environment information."""
        try:
            result = await run_shell(
                "uname -a; echo '---'; id; echo '---'; pwd; echo '---'; python3 --version; git --version",
                cwd=".",
                timeout_s=10,
            )
            return _ok(
                {
                    "settings": safe_settings_dump(settings),
                    "probe": result.model_dump(),
                }
            )
        except Exception as exc:
            return _handled_error(exc)
