"""Todo MCP tool registry."""

import asyncio

from ...ops.todo import read_todos_execute, write_todos_execute
from ...schemas.input_models.todo import TodosArg
from ...schemas.result_models.todo import ReadTodosOutput, WriteTodosOutput
from ..declarative import DeclarativeToolRegistry


class TodoToolRegistry(DeclarativeToolRegistry):
    """Register todo-list tools."""

    name = "todo"


local_tool = TodoToolRegistry.get_tool_decorator()


@local_tool(http_method="GET", http_path="/tools/todo")
async def read_todos() -> ReadTodosOutput:
    """Read the current agent todo list."""
    return await asyncio.to_thread(read_todos_execute)


@local_tool(http_method="POST", http_path="/tools/todo")
async def write_todos(todos: TodosArg) -> WriteTodosOutput:
    """Replace the current structured agent todo list."""
    return await asyncio.to_thread(write_todos_execute, todos)
