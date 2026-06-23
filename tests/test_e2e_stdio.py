import pytest

from tests.e2e_helpers import stdio_tool_client
from tests.e2e_scenarios import (
    assert_core_tool_surface,
    exercise_environment_tool,
    exercise_explicit_session_workflow,
    exercise_filesystem_and_search_tools,
    exercise_interactive_shell_tools,
    exercise_shell_tools,
    exercise_todo_tools,
    exercise_workspace_connector_tools,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_stdio_process_exercises_core_tool_categories(tmp_path):
    async with stdio_tool_client(tmp_path) as (client, workspace):
        await assert_core_tool_surface(client)
        await exercise_environment_tool(client, workspace)
        await exercise_explicit_session_workflow(client, workspace)
        await exercise_filesystem_and_search_tools(client, workspace)
        await exercise_workspace_connector_tools(client)
        await exercise_shell_tools(client)
        await exercise_interactive_shell_tools(client)
        await exercise_todo_tools(client)
