"""Todo MCP tool registry."""

import asyncio

from ...ops.todo_ops import read_todos_execute, write_todos_execute
from ..declarative import DeclarativeToolRegistry
from ..inputs.todo import TodosArg
from ..outputs.todo import ReadTodosOutput, WriteTodosOutput


class TodoToolRegistry(DeclarativeToolRegistry):
    """Register todo-list tools."""

    name = "todo"


local_tool = TodoToolRegistry.get_tool_decorator()


@local_tool(http_method="GET", http_path="/tools/todo")
async def read_todos() -> ReadTodosOutput:
    """Read the current agent todo list."""
    return ReadTodosOutput.model_validate(
        await asyncio.to_thread(read_todos_execute)
    )


@local_tool(http_method="POST", http_path="/tools/todo")
async def write_todos(todos: TodosArg) -> WriteTodosOutput:
    """Replace the current structured agent todo list."""
    return WriteTodosOutput.model_validate(
        await asyncio.to_thread(write_todos_execute, todos)
    )
