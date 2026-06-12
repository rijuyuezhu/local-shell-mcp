"""Todo MCP tool registry."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...ops.todo_ops import todo_read, todo_write
from ..base import HttpToolRoute, McpToolContext, ToolHandler, ToolRegistry
from ..responses import handled_error, ok_response, to_thread


async def _todo_read_tool(args: dict[str, Any]) -> dict[str, Any]:
    return await to_thread(todo_read)


async def _todo_write_tool(args: dict[str, Any]) -> dict[str, Any]:
    return await to_thread(todo_write, args.get("todos", []))


TODO_HTTP_ROUTES = (
    HttpToolRoute("GET", "/tools/todo", "todo_read_tool"),
    HttpToolRoute("POST", "/tools/todo", "todo_write_tool"),
)

TODO_HTTP_HANDLERS: dict[str, ToolHandler] = {
    "todo_read_tool": _todo_read_tool,
    "todo_write_tool": _todo_write_tool,
}


class TodoToolRegistry(ToolRegistry):
    """Register todo-list tools."""

    name = "todo"

    def http_routes(self):
        return TODO_HTTP_ROUTES

    def http_handlers(self):
        return TODO_HTTP_HANDLERS

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_todo_mcp(mcp, context)


def register_todo_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register MCP tools for this tool group."""
    protected_meta = context.protected_meta

    @mcp.tool(meta=protected_meta)
    async def todo_read_tool() -> dict:
        """Read the current agent todo list. Use at the start of multi-step or resumed work to recover planned tasks and statuses. This is read-only; use todo_write_tool to create or update todos."""
        try:
            return ok_response(await to_thread(todo_read))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=protected_meta)
    async def todo_write_tool(todos: list[dict]) -> dict:
        """Replace the current structured agent todo list. Use for multi-step work where progress should be tracked explicitly. Each todo should include id, content, status, and priority; keep statuses current rather than storing unrelated notes."""
        try:
            return ok_response(await to_thread(todo_write, todos))
        except Exception as exc:
            return handled_error(exc)
