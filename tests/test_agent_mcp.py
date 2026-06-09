from types import SimpleNamespace

import pytest

from local_shell_mcp.agent_bridge import AgentMcpServerConfig
from local_shell_mcp.agent_mcp import (
    AgentMcpClientManager,
    AgentMcpTool,
    normalize_mcp_tool,
    normalize_tool_result,
)


def test_normalize_mcp_tool_preserves_schema():
    sdk_tool = SimpleNamespace(
        name="search",
        description="Search docs",
        inputSchema={"type": "object", "properties": {"query": {"type": "string"}}},
    )

    assert normalize_mcp_tool(sdk_tool) == AgentMcpTool(
        name="search",
        description="Search docs",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
    )


def test_normalize_tool_result_handles_text_content():
    result = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="hello")],
        structuredContent=None,
        isError=False,
    )

    assert normalize_tool_result(result) == {
        "is_error": False,
        "content": [{"type": "text", "text": "hello"}],
        "structured_content": None,
    }


@pytest.mark.asyncio
async def test_client_manager_rejects_missing_stdio_command():
    manager = AgentMcpClientManager(call_timeout_s=1)
    server = AgentMcpServerConfig(type="stdio")

    with pytest.raises(ValueError, match="stdio MCP server requires command"):
        await manager.list_tools("broken", server)


@pytest.mark.asyncio
async def test_client_manager_rejects_missing_http_url():
    manager = AgentMcpClientManager(call_timeout_s=1)
    server = AgentMcpServerConfig(type="http")

    with pytest.raises(ValueError, match="http MCP server requires url"):
        await manager.list_tools("broken", server)
