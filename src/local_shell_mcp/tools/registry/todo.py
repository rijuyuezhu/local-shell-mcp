"""Todo MCP tool registry."""

import asyncio

from ...ops.todo_ops import todo_read as read_todos_execute
from ...ops.todo_ops import todo_write as write_todos_execute
from ..declarative import DeclarativeToolRegistry


class TodoToolRegistry(DeclarativeToolRegistry):
    """Register todo-list tools."""

    name = "todo"


local_tool = TodoToolRegistry.get_tool_decorator()


@local_tool(http_method="GET", http_path="/tools/todo")
async def read_todos() -> dict:
    """Read the current agent todo list. Use at the start of multi-step or resumed work to recover planned tasks and statuses. This is read-only; use write_todos to create or update todos."""
    return await asyncio.to_thread(read_todos_execute)


@local_tool(http_method="POST", http_path="/tools/todo")
async def write_todos(todos: list[dict]) -> dict:
    """Replace the current structured agent todo list. Use for multi-step work where progress should be tracked explicitly. Each todo should include id, content, status, and priority; keep statuses current and omit unrelated notes."""
    return await asyncio.to_thread(write_todos_execute, todos)
