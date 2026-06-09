import json

import pytest

import local_shell_mcp.tools as tools_module
from local_shell_mcp.agent_mcp import AgentMcpTool
from local_shell_mcp.settings import get_settings
from local_shell_mcp.tools import build_mcp


def _payload(response):  # noqa: ANN001
    return json.loads(response[0].text)


@pytest.mark.asyncio
async def test_fixed_bridge_tools_exist_with_missing_config(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(tmp_path / "agent-config"))
    get_settings.cache_clear()

    mcp = build_mcp()
    tools = {tool.name for tool in await mcp.list_tools()}

    assert "agent_config_status" in tools
    assert "list_agent_skills" in tools
    assert "activate_agent_skill" in tools
    assert "list_agent_mcp_servers" in tools
    assert "list_agent_mcp_tools" in tools
    assert "call_agent_mcp_tool" in tools


@pytest.mark.asyncio
async def test_agent_config_status_reports_missing_config(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(tmp_path / "agent-config"))
    get_settings.cache_clear()

    response = await build_mcp().call_tool("agent_config_status", {})
    payload = response[0].text

    assert "missing_config" in payload


@pytest.mark.asyncio
async def test_activate_agent_skill_returns_skill_content(tmp_path, monkeypatch):
    config_dir = tmp_path / "agent-config"
    skill_dir = config_dir / "skills" / "debugging"
    skill_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(json.dumps({"version": 1}), encoding="utf-8")
    (skill_dir / "SKILL.md").write_text("# Debugging\n\nFind root causes.\n", encoding="utf-8")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    response = await build_mcp().call_tool("activate_agent_skill", {"name": "debugging"})
    payload = response[0].text

    assert "Find root causes." in payload
    assert "skills/debugging/SKILL.md" in payload


@pytest.mark.asyncio
async def test_agent_mcp_fixed_tools_route_and_reject_unavailable_servers(tmp_path, monkeypatch):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "docs": {"type": "http", "url": "https://docs.example/mcp"},
                    "bad": {"type": "http", "url": "https://bad.example/mcp"},
                    "off": {
                        "type": "http",
                        "url": "https://off.example/mcp",
                        "enabled": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeMcpClientManager:
        def __init__(self):
            self.list_calls = []
            self.call_calls = []

        async def list_tools(self, name, server):  # noqa: ANN001
            self.list_calls.append((name, server.url))
            if name == "bad":
                raise RuntimeError("probe failed")
            return [
                AgentMcpTool(
                    name="search",
                    description="Search docs",
                    input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
                )
            ]

        async def call_tool(self, name, server, tool, args):  # noqa: ANN001
            self.call_calls.append((name, server.url, tool, args))
            return {"server": name, "tool": tool, "args": args}

    fake_manager = FakeMcpClientManager()
    monkeypatch.setattr(tools_module, "AgentMcpClientManager", lambda _timeout: fake_manager)
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    mcp = build_mcp()

    servers = _payload(await mcp.call_tool("list_agent_mcp_servers", {}))["data"]
    assert set(servers) == {"docs", "bad", "off"}
    assert servers["docs"]["available"] is True
    assert servers["bad"]["available"] is False
    assert servers["off"]["available"] is False

    tools = _payload(await mcp.call_tool("list_agent_mcp_tools", {}))["data"]["tools"]
    assert tools == [
        {
            "server": "docs",
            "tool": "search",
            "description": "Search docs",
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
            "dynamic_tool_name": "agent_mcp__docs__search",
        }
    ]

    result = _payload(
        await mcp.call_tool(
            "call_agent_mcp_tool",
            {"server": "docs", "tool": "search", "args": {"query": "mcp"}},
        )
    )
    assert result["data"] == {"server": "docs", "tool": "search", "args": {"query": "mcp"}}
    assert fake_manager.call_calls == [
        ("docs", "https://docs.example/mcp", "search", {"query": "mcp"})
    ]

    disabled = _payload(
        await mcp.call_tool("call_agent_mcp_tool", {"server": "off", "tool": "search", "args": {}})
    )
    assert disabled["data"]["error_type"] == "ValueError"
    assert disabled["data"]["message"] == "MCP server off is disabled"

    unavailable = _payload(
        await mcp.call_tool("call_agent_mcp_tool", {"server": "bad", "tool": "search", "args": {}})
    )
    assert unavailable["data"]["error_type"] == "ValueError"
    assert unavailable["data"]["message"] == (
        "MCP server bad is unavailable: RuntimeError: probe failed"
    )

    unknown = _payload(
        await mcp.call_tool(
            "call_agent_mcp_tool", {"server": "missing", "tool": "search", "args": {}}
        )
    )
    assert unknown["data"]["error_type"] == "ValueError"
    assert unknown["data"]["message"] == "Unknown agent MCP server: missing"
    assert fake_manager.call_calls == [
        ("docs", "https://docs.example/mcp", "search", {"query": "mcp"})
    ]


@pytest.mark.asyncio
async def test_call_agent_mcp_tool_redacts_unavailable_probe_error(tmp_path, monkeypatch):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "bad": {"type": "http", "url": "https://bad.example/mcp"},
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeMcpClientManager:
        async def list_tools(self, name, server):  # noqa: ANN001, ARG002
            raise RuntimeError(
                "Authorization: Bearer super-secret --token super-secret "
                "https://example.com?token=super-secret "
                '{"api_key": "super-secret"} '
                "{'token': 'super-secret'} "
                '["--token", "super-secret"] '
                "['--token', 'super-secret'] "
                "https://user:super-secret@example.com/path"
            )

        async def call_tool(self, name, server, tool, args):  # noqa: ANN001, ARG002
            raise AssertionError("unavailable server should not be called")

    monkeypatch.setattr(
        tools_module, "AgentMcpClientManager", lambda _timeout: FakeMcpClientManager()
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    response = await build_mcp().call_tool(
        "call_agent_mcp_tool", {"server": "bad", "tool": "search", "args": {}}
    )
    payload = response[0].text

    assert "super-secret" not in payload
    assert "<redacted>" in payload


@pytest.mark.asyncio
async def test_call_agent_mcp_tool_redacts_call_error(tmp_path, monkeypatch):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "docs": {"type": "http", "url": "https://docs.example/mcp"},
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeMcpClientManager:
        async def list_tools(self, name, server):  # noqa: ANN001, ARG002
            return [
                AgentMcpTool(
                    name="search",
                    description="Search docs",
                    input_schema={"type": "object"},
                )
            ]

        async def call_tool(self, name, server, tool, args):  # noqa: ANN001, ARG002
            raise RuntimeError(
                "Authorization: Bearer call-secret --token call-secret "
                "https://example.com?token=call-secret "
                '{"api_key": "call-secret"} '
                "{'token': 'call-secret'} "
                '["--token", "call-secret"] '
                "['--token', 'call-secret'] "
                "https://user:call-secret@example.com/path"
            )

    monkeypatch.setattr(
        tools_module, "AgentMcpClientManager", lambda _timeout: FakeMcpClientManager()
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    response = await build_mcp().call_tool(
        "call_agent_mcp_tool", {"server": "docs", "tool": "search", "args": {}}
    )
    payload = response[0].text

    assert "call-secret" not in payload
    assert "<redacted>" in payload


class FakeDynamicMcpManager:
    async def list_tools(self, name, server):  # noqa: ANN001, ARG002
        if name == "docs":
            return [
                AgentMcpTool(
                    name="search",
                    description="Search docs",
                    input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
                )
            ]
        return []

    async def call_tool(self, name, server, tool, args):  # noqa: ANN001, ARG002
        return {
            "server": name,
            "tool": tool,
            "args": args,
            "content": [{"type": "text", "text": "ok"}],
        }


@pytest.mark.asyncio
async def test_dynamic_skill_tool_is_visible_and_callable(tmp_path, monkeypatch):
    config_dir = tmp_path / "agent-config"
    skill_dir = config_dir / "skills" / "paper-writer"
    skill_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(json.dumps({"version": 1}), encoding="utf-8")
    (skill_dir / "SKILL.md").write_text("# Paper Writer\n\nDraft papers.\n", encoding="utf-8")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    mcp = build_mcp()
    tools = {tool.name for tool in await mcp.list_tools()}

    assert "activate_skill__paper_writer" in tools
    response = await mcp.call_tool("activate_skill__paper_writer", {})
    assert "Draft papers." in response[0].text


@pytest.mark.asyncio
async def test_dynamic_mcp_tool_is_visible_and_callable(tmp_path, monkeypatch):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {"docs": {"type": "http", "url": "https://example.com/mcp"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(
        tools_module, "AgentMcpClientManager", lambda timeout: FakeDynamicMcpManager()
    )
    get_settings.cache_clear()

    mcp = build_mcp()
    tool_names = {tool.name for tool in await mcp.list_tools()}

    assert "agent_mcp__docs__search" in tool_names
    response = await mcp.call_tool("agent_mcp__docs__search", {"args": {"query": "abc"}})
    assert "abc" in response[0].text
