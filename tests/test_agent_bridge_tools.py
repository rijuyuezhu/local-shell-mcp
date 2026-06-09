import json

import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.tools import build_mcp


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
