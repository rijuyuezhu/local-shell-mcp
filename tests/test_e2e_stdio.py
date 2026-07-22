import pytest

from tests.e2e_helpers import stdio_tool_client
from tests.e2e_scenarios import (
    assert_core_tool_surface,
    exercise_environment_tool,
    exercise_explicit_session_workflow,
    exercise_filesystem_and_search_tools,
    exercise_interactive_shell_tools,
    exercise_session_bound_job_tools,
    exercise_session_copy_tool,
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
        await exercise_session_copy_tool(client, workspace)
        await exercise_workspace_connector_tools(client)
        await exercise_shell_tools(client, workspace)
        await exercise_session_bound_job_tools(client, workspace)
        await exercise_interactive_shell_tools(client)
        await exercise_todo_tools(client)


@pytest.mark.asyncio
async def test_stdio_process_diagnoses_stale_tool_snapshot(tmp_path):
    async with stdio_tool_client(tmp_path) as (client, _workspace):
        listed = await client.list_tools()
        assert "remote_run_shell_tool" not in listed

        result = await client.call_tool(
            "remote_run_shell_tool", {"machine": "worker"}
        )

        assert result["ok"] is False
        assert result["data"]["status"] == "stale_tool_snapshot"
        assert result["data"]["replacement"] == "bash"
        assert (
            "session_start(target='remote'"
            in result["data"]["assistant_instruction"]
        )


@pytest.mark.asyncio
async def test_stdio_process_returns_native_image_content(tmp_path):
    import base64

    from mcp.types import ImageContent

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lP7LAAAAAElFTkSuQmCC"
    )
    async with stdio_tool_client(tmp_path) as (client, workspace):
        (workspace / "pixel.png").write_bytes(png)
        session = await client.call_tool("session_start", {"workdir": "."})

        result = await client.call_tool_result(
            "view_image",
            {"session_id": session["session_id"], "path": "pixel.png"},
        )

        assert result.isError is False
        assert isinstance(result.content[0], ImageContent)
        assert base64.b64decode(result.content[0].data) == png
        assert result.structuredContent == {
            "session_id": session["session_id"],
            "target": "local",
            "machine": None,
            "path": "pixel.png",
            "mime_type": "image/png",
            "bytes": len(png),
        }
