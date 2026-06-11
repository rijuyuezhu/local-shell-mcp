"""Shell MCP tool registry."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..base import HttpToolRoute, McpToolContext, ToolRegistry
from .local import register_shell_mcp


class ShellToolRegistry(ToolRegistry):
    """Register shell execution and session tools."""

    name = "shell"

    def http_routes(self):
        from ..local_invocations import HTTP_TOOL_ROUTES

        names = {
            "run_shell_tool",
            "run_python_tool",
            "shell_start",
            "shell_send",
            "shell_read",
            "shell_kill",
            "shell_list",
        }
        return (
            HttpToolRoute(method=method, path=path, tool_name=tool_name)
            for (method, path), tool_name in HTTP_TOOL_ROUTES.items()
            if tool_name in names
        )

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_shell_mcp(mcp, context)
