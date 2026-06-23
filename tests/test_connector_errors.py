import asyncio

import pytest

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.server.mcp.app import build_mcp
from local_shell_mcp.tools.registry import (
    workspace_connector as workspace_connector_tools,
)
from tests.helpers import mcp_structured


@pytest.mark.asyncio
async def test_connector_tools_use_custom_mcp_error_handler(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    async def failing_search(query: str):
        raise ValueError("search failed")

    async def failing_fetch(id: str):
        raise ValueError("fetch failed")

    monkeypatch.setattr(
        workspace_connector_tools, "search_execute", failing_search
    )
    monkeypatch.setattr(
        workspace_connector_tools, "fetch_execute", failing_fetch
    )

    mcp = build_mcp()

    search_payload = mcp_structured(
        await mcp.call_tool("workspace_search", {"query": "needle"})
    )
    fetch_payload = mcp_structured(
        await mcp.call_tool("fetch", {"id": "notes/demo.txt"})
    )

    assert search_payload == {"results": []}
    assert fetch_payload["id"] == "notes/demo.txt"
    assert fetch_payload["title"] == "notes/demo.txt"
    assert "ValueError: fetch failed" in fetch_payload["text"]
    assert fetch_payload["metadata"]["error"] == "ValueError"


@pytest.mark.asyncio
async def test_connector_tool_timeout_uses_custom_mcp_error_handler(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_TOOL_TIMEOUT_S", "0.01")
    clear_settings_cache()

    async def hanging_search(query: str):
        await asyncio.sleep(5)

    async def hanging_fetch(id: str):
        await asyncio.sleep(5)

    monkeypatch.setattr(
        workspace_connector_tools, "search_execute", hanging_search
    )
    monkeypatch.setattr(
        workspace_connector_tools, "fetch_execute", hanging_fetch
    )

    mcp = build_mcp()

    search_payload = mcp_structured(
        await mcp.call_tool("workspace_search", {"query": "needle"})
    )
    fetch_payload = mcp_structured(
        await mcp.call_tool("fetch", {"id": "notes/demo.txt"})
    )

    assert search_payload == {"results": []}
    assert fetch_payload["id"] == "notes/demo.txt"
    assert "fetch exceeded 0.01 second tool timeout" in fetch_payload["text"]
    assert fetch_payload["metadata"]["error"] == "PublicToolTimeoutError"
