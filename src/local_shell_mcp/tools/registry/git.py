"""Git MCP tool registry."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..base import HttpToolRoute, McpToolContext, ToolRegistry
from .local import register_git_mcp


class GitToolRegistry(ToolRegistry):
    """Register git operation tools."""

    name = "git"

    def http_routes(self):
        from ..local_invocations import HTTP_TOOL_ROUTES

        names = {
            "git_clone_tool",
            "git_status_tool",
            "git_diff_tool",
            "git_log_tool",
            "git_checkout_tool",
            "git_fetch_tool",
            "git_pull_tool",
            "git_add_tool",
            "git_commit_tool",
            "git_push_tool",
            "git_show_tool",
            "git_reset_tool",
        }
        return (
            HttpToolRoute(method=method, path=path, tool_name=tool_name)
            for (method, path), tool_name in HTTP_TOOL_ROUTES.items()
            if tool_name in names
        )

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_git_mcp(mcp, context)
