import json
import time

import pytest

from local_shell_mcp.agent_bridge.mcp import AgentMcpTool
from local_shell_mcp.auth.oauth import (
    issue_access_token,
    resource_url,
    validate_bearer_token,
)
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.mcp_app import build_mcp
from local_shell_mcp.tools.registry import agent as tools_module


def test_oauth_resource_defaults_to_mcp_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://local-shell-mcp.example.com"
    )
    monkeypatch.delenv("LOCAL_SHELL_MCP_OAUTH_RESOURCE", raising=False)
    clear_settings_cache()

    assert resource_url() == "https://local-shell-mcp.example.com/mcp"


@pytest.mark.asyncio
async def test_mcp_metadata_for_chatgpt_developer_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://local-shell-mcp.example.com"
    )
    clear_settings_cache()

    mcp = build_mcp()
    transport_security = mcp.settings.transport_security
    assert transport_security is not None
    assert "local-shell-mcp.example.com" in transport_security.allowed_hosts

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    search_meta = tools["search"].meta
    environment_meta = tools["environment_info"].meta
    assert search_meta is not None
    assert environment_meta is not None
    assert search_meta["securitySchemes"][0]["type"] == "noauth"
    assert environment_meta["securitySchemes"][0]["type"] == "oauth2"


@pytest.mark.asyncio
async def test_full_container_mode_marks_command_tools_for_auto_approval(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "true")
    clear_settings_cache()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    annotations = tools["run_shell_tool"].annotations
    search_annotations = tools["search"].annotations
    assert annotations is not None
    assert search_annotations is not None
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is False
    assert annotations.openWorldHint is False

    assert search_annotations.readOnlyHint is True


@pytest.mark.asyncio
async def test_full_container_mode_does_not_auto_approve_agent_mcp_proxies(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "docs": {"type": "http", "url": "https://docs.example/mcp"}
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
            return {"ok": True}

    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "true")
    monkeypatch.setattr(
        tools_module,
        "AgentMcpClientManager",
        lambda _timeout: FakeMcpClientManager(),
    )
    clear_settings_cache()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    run_shell_annotations = tools["run_shell_tool"].annotations
    assert run_shell_annotations is not None
    assert run_shell_annotations.openWorldHint is False
    assert tools["call_agent_mcp_tool"].annotations is None
    assert tools["agent_mcp__docs__search"].annotations is None


@pytest.mark.asyncio
async def test_default_mode_does_not_mark_command_tools_for_auto_approval(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "false")
    clear_settings_cache()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    assert tools["run_shell_tool"].annotations is None


def test_oauth_access_tokens_expire_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.delenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("LOCAL_SHELL_MCP_OAUTH_ISSUER", raising=False)
    monkeypatch.delenv("LOCAL_SHELL_MCP_OAUTH_RESOURCE", raising=False)
    clear_settings_cache()

    token = issue_access_token(
        client_id="test-client",
        scope="shell:execute",
        resource="http://127.0.0.1:8765/mcp",
    )
    claims = validate_bearer_token(token)

    assert claims["exp"] > int(time.time())
    assert claims["client_id"] == "test-client"
