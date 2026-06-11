"""Todo MCP tool registry."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ...ops.todo_ops import todo_read, todo_write
from ..base import HttpToolRoute, McpToolContext, ToolRegistry
from .common import handled_error, ok_response, to_thread


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


def register_todo_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register MCP tools for this tool group."""
    oauth_meta = context.oauth_meta

    @mcp.tool(meta=oauth_meta)
    async def todo_read_tool() -> dict:
        """Read the agent todo list. Similar to Claude Code TodoRead."""
        try:
            return ok_response(await to_thread(todo_read))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def todo_write_tool(todos: list[dict]) -> dict:
        """Write the agent todo list. Each todo: id, content, status, priority."""
        try:
            return ok_response(await to_thread(todo_write, todos))
        except Exception as exc:
            return handled_error(exc)
