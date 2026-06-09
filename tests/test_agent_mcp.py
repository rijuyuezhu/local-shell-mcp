import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from mcp.types import Tool

from local_shell_mcp.agent_bridge import AgentMcpServerConfig, build_agent_registry
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


def test_normalize_mcp_tool_handles_sdk_tool_model():
    sdk_tool = Tool(
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


@pytest.mark.asyncio
async def test_client_manager_list_tools_accumulates_paginated_pages(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.cursors = []

        async def list_tools(self, cursor=None):
            self.cursors.append(cursor)
            if cursor is None:
                return SimpleNamespace(
                    tools=[
                        SimpleNamespace(
                            name="search",
                            description="Search docs",
                            inputSchema={"type": "object"},
                        )
                    ],
                    nextCursor="next-page",
                )
            if cursor == "next-page":
                return SimpleNamespace(
                    tools=[
                        SimpleNamespace(
                            name="fetch",
                            description="Fetch doc",
                            inputSchema={"type": "object"},
                        )
                    ]
                )
            raise AssertionError(f"unexpected cursor: {cursor}")

    manager = AgentMcpClientManager(call_timeout_s=1)
    server = AgentMcpServerConfig(type="http", url="https://example.test/mcp")
    session = FakeSession()

    @asynccontextmanager
    async def fake_session(name, session_server):
        assert name == "docs"
        assert session_server is server
        yield session

    monkeypatch.setattr(manager, "_session", fake_session)

    assert await manager.list_tools("docs", server) == [
        AgentMcpTool("search", "Search docs", {"type": "object"}),
        AgentMcpTool("fetch", "Fetch doc", {"type": "object"}),
    ]
    assert session.cursors == [None, "next-page"]


@pytest.mark.asyncio
async def test_client_manager_call_tool_uses_session_and_normalizes_result(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.calls = []

        async def call_tool(self, tool, args):
            self.calls.append((tool, args))
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="done")],
                structuredContent={"ok": True},
                isError=False,
            )

    manager = AgentMcpClientManager(call_timeout_s=1)
    server = AgentMcpServerConfig(type="http", url="https://example.test/mcp")
    session = FakeSession()

    @asynccontextmanager
    async def fake_session(name, session_server):
        assert name == "docs"
        assert session_server is server
        yield session

    monkeypatch.setattr(manager, "_session", fake_session)

    assert await manager.call_tool("docs", server, "search", {"query": "mcp"}) == {
        "is_error": False,
        "content": [{"type": "text", "text": "done"}],
        "structured_content": {"ok": True},
    }
    assert session.calls == [("search", {"query": "mcp"})]


@pytest.mark.asyncio
async def test_client_manager_list_tools_cleans_up_session_on_use_error(monkeypatch):
    events = []

    class FakeSession:
        async def list_tools(self, cursor=None):
            events.append(("list_tools", cursor))
            raise RuntimeError("list failed")

    manager = AgentMcpClientManager(call_timeout_s=1)
    server = AgentMcpServerConfig(type="http", url="https://example.test/mcp")

    @asynccontextmanager
    async def fake_session(name, session_server):
        assert name == "docs"
        assert session_server is server
        events.append("enter")
        try:
            yield FakeSession()
        finally:
            events.append("exit")

    monkeypatch.setattr(manager, "_session", fake_session)

    with pytest.raises(RuntimeError, match="list failed"):
        await manager.list_tools("docs", server)

    assert events == ["enter", ("list_tools", None), "exit"]


class FakeMcpManager:
    def __init__(self, tools_by_server=None, errors_by_server=None):
        self.tools_by_server = tools_by_server or {}
        self.errors_by_server = errors_by_server or {}

    async def list_tools(self, name, server):  # noqa: ANN001
        if name in self.errors_by_server:
            raise self.errors_by_server[name]
        return self.tools_by_server.get(name, [])


def test_build_agent_registry_probes_enabled_servers(tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "docs": {"type": "http", "url": "https://example.com/mcp"},
                    "off": {
                        "type": "http",
                        "url": "https://example.com/mcp",
                        "enabled": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    manager = FakeMcpManager(
        tools_by_server={
            "docs": [
                AgentMcpTool(
                    name="search",
                    description="Search docs",
                    input_schema={"type": "object"},
                )
            ]
        }
    )

    registry = build_agent_registry(tmp_path, manager, probe_timeout_s=1)

    assert registry.manifest_status == "loaded"
    assert registry.mcp_servers["docs"].available is True
    assert registry.mcp_servers["docs"].tools[0].name == "search"
    assert registry.mcp_servers["off"].available is False
    assert registry.mcp_servers["off"].error == "disabled"


def test_build_agent_registry_records_probe_errors(tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps(
            {"version": 1, "mcpServers": {"bad": {"type": "http", "url": "https://bad"}}}
        ),
        encoding="utf-8",
    )

    registry = build_agent_registry(
        tmp_path,
        FakeMcpManager(errors_by_server={"bad": RuntimeError("boom")}),
        probe_timeout_s=1,
    )

    assert registry.mcp_servers["bad"].available is False
    assert registry.mcp_servers["bad"].error == "RuntimeError: boom"
