"""Todo MCP tool registry."""

import asyncio

from ...ops.todo import read_todos_execute, write_todos_execute
from ...schemas.input_models.session import SessionIdArg
from ...schemas.input_models.todo import TodosArg
from ...schemas.result_models.todo import ReadTodosOutput, WriteTodosOutput
from ..declarative import DeclarativeToolRegistry


class TodoToolRegistry(DeclarativeToolRegistry):
    """Register todo-list tools."""

    name = "todo"
    """Registry group name used for tool-surface organization."""


local_tool = TodoToolRegistry.get_tool_decorator()


@local_tool(
    http_method="GET",
    http_path="/tools/todo",
    annotations="read_only",
    oauth_scopes=("shell:read",),
)
async def read_todos(session_id: SessionIdArg) -> ReadTodosOutput:
    """Read the structured todo list owned by one explicit agent/workspace session. Pass the session_id returned by session_start. Use this when resuming or checking multi-step work in the current session before deciding what to do next. Todos are session-scoped: items from one session are not shared with another local or remote session, and shell_id/job_id values are not valid here. For changing the list, use write_todos with the complete replacement list."""
    return await asyncio.to_thread(read_todos_execute, session_id)


@local_tool(
    http_method="POST",
    http_path="/tools/todo",
    oauth_scopes=("shell:read", "shell:write"),
)
async def write_todos(
    session_id: SessionIdArg, todos: TodosArg
) -> WriteTodosOutput:
    """Replace the structured todo list owned by one explicit agent/workspace session. Pass the session_id returned by session_start and provide the full desired todo list, not a partial patch; omitted existing items are removed. Use this for multi-step coding work where tracking in_progress/completed/pending items helps coordinate the current session. Keep todo content concise and actionable, and use read_todos first when preserving existing items matters."""
    return await asyncio.to_thread(write_todos_execute, todos, session_id)
