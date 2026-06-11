"""Todo MCP tool registry."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..base import HttpToolRoute, McpToolContext, ToolRegistry
from .local import register_todo_mcp


class TodoToolRegistry(ToolRegistry):
    """Register todo-list tools."""

    name = "todo"

    def http_routes(self):
        from ..local_invocations import HTTP_TOOL_ROUTES

        names = {"todo_read_tool", "todo_write_tool"}
        return (
            HttpToolRoute(method=method, path=path, tool_name=tool_name)
            for (method, path), tool_name in HTTP_TOOL_ROUTES.items()
            if tool_name in names
        )

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_todo_mcp(mcp, context)
