import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette

from local_shell_mcp.agent_bridge.mcp import AgentMcpTool
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.oauth.authorization import _authorize_form
from local_shell_mcp.oauth.routes import wrap_http_app
from local_shell_mcp.oauth.tokens import (
    issue_access_token,
    validate_bearer_token,
)
from local_shell_mcp.oauth.urls import resource_url
from local_shell_mcp.server.mcp.app import (
    _transport_security_settings,
    build_mcp,
)
from local_shell_mcp.tools.registry import agent as tools_module
from tests.helpers import mcp_structured


def test_oauth_resource_defaults_to_mcp_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_BASE_URL", "https://local-shell-mcp.example.com"
    )
    monkeypatch.delenv("LOCAL_SHELL_MCP_OAUTH_RESOURCE", raising=False)
    clear_settings_cache()

    assert resource_url() == "https://local-shell-mcp.example.com/mcp"


@pytest.mark.asyncio
async def test_mcp_metadata_for_chatgpt_developer_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_BASE_URL", "https://local-shell-mcp.example.com"
    )
    clear_settings_cache()

    mcp = build_mcp()
    assert mcp.instructions is not None
    assert (
        "Dedicated git tools are intentionally not exposed" in mcp.instructions
    )
    assert "secret_scan is heuristic" in mcp.instructions

    transport_security = mcp.settings.transport_security
    assert transport_security is not None
    assert "local-shell-mcp.example.com" in transport_security.allowed_hosts
    assert "local-shell-mcp.example.com:443" in transport_security.allowed_hosts
    assert (
        "local-shell-mcp.example.com:*" not in transport_security.allowed_hosts
    )

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    search_meta = tools["search"].meta
    environment_meta = tools["environment_info"].meta
    assert search_meta is not None
    assert environment_meta is not None
    assert search_meta["securitySchemes"][0]["type"] == "noauth"
    assert environment_meta["securitySchemes"][0]["type"] == "oauth2"

    assert all(tool.outputSchema is not None for tool in tools.values())
    run_shell_command_schema = tools["run_shell_command"].outputSchema
    assert run_shell_command_schema is not None
    assert run_shell_command_schema["title"] == "ToolResult"
    assert set(run_shell_command_schema["properties"]) == {
        "ok",
        "message",
        "data",
    }
    search_schema = tools["search"].outputSchema
    assert search_schema is not None
    assert "results" in search_schema["properties"]
    fetch_schema = tools["fetch"].outputSchema
    assert fetch_schema is not None
    assert set(fetch_schema["properties"]) == {
        "id",
        "title",
        "text",
        "url",
        "metadata",
    }

    structured = mcp_structured(await mcp.call_tool("environment_info", {}))
    assert structured["ok"] is True
    assert "workspace_root" in structured["data"]["settings"]


@pytest.mark.asyncio
async def test_tool_descriptions_include_runtime_limits(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_OUTPUT_BYTES", "12345")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_GREP_RESULTS", "678")
    clear_settings_cache()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    run_shell_command_description = tools["run_shell_command"].description or ""
    grep_description = tools["grep_search"].description or ""
    assert "max_output_bytes=12345" in run_shell_command_description
    assert "max_grep_results=678" in grep_description


def test_transport_security_uses_exact_base_url_host(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_BASE_URL", "https://example.com:8443")
    clear_settings_cache()

    transport_security = _transport_security_settings()

    assert "example.com:8443" in transport_security.allowed_hosts
    assert "example.com" not in transport_security.allowed_hosts
    assert "example.com:*" not in transport_security.allowed_hosts
    assert "https://example.com:8443" in transport_security.allowed_origins
    assert "https://example.com" not in transport_security.allowed_origins


def test_transport_security_handles_default_ports_and_ipv6(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_BASE_URL", "https://[2001:db8::1]:443")
    clear_settings_cache()

    transport_security = _transport_security_settings()

    assert "[2001:db8::1]" in transport_security.allowed_hosts
    assert "[2001:db8::1]:443" in transport_security.allowed_hosts
    assert "2001:db8::1:*" not in transport_security.allowed_hosts
    assert "[2001:db8::1]:*" not in transport_security.allowed_hosts
    assert "https://[2001:db8::1]" in transport_security.allowed_origins


@pytest.mark.asyncio
async def test_full_container_mode_marks_command_tools_with_relaxed_client_hints(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL", "true")
    clear_settings_cache()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    annotations = tools["run_shell_command"].annotations
    search_annotations = tools["search"].annotations
    assert annotations is not None
    assert search_annotations is not None
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is False
    assert annotations.openWorldHint is False

    assert search_annotations.readOnlyHint is True


@pytest.mark.asyncio
async def test_relaxed_client_hints_do_not_apply_to_agent_mcp_proxies(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / ".local-shell-mcp" / "agent_config"
    config_dir.mkdir(parents=True)
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
        async def list_tools(self, name, server):
            return [
                AgentMcpTool(
                    name="search",
                    description="Search docs",
                    input_schema={"type": "object"},
                )
            ]

        async def call_tool(self, name, server, tool, args):
            return {"ok": True}

    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(config_dir.parent))
    monkeypatch.setenv("LOCAL_SHELL_MCP_RELAXED_CLIENT_TOOL_HINTS", "true")
    monkeypatch.setattr(
        tools_module,
        "AgentMcpClientManager",
        lambda _timeout: FakeMcpClientManager(),
    )
    clear_settings_cache()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    run_shell_command_annotations = tools["run_shell_command"].annotations
    assert run_shell_command_annotations is not None
    assert run_shell_command_annotations.openWorldHint is False
    assert tools["call_agent_mcp_tool"].annotations is None
    assert tools["agent_mcp__docs__search"].annotations is None


@pytest.mark.asyncio
async def test_relaxed_client_tool_hints_marks_command_tools_without_full_container(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_RELAXED_CLIENT_TOOL_HINTS", "true")
    clear_settings_cache()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    annotations = tools["run_shell_command"].annotations
    assert annotations is not None
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is False
    assert annotations.openWorldHint is False
    assert tools["run_shell_command"].meta == {
        "securitySchemes": [
            {
                "type": "oauth2",
                "scopes": [
                    "shell:read",
                    "shell:write",
                    "shell:execute",
                ],
            }
        ]
    }


@pytest.mark.asyncio
async def test_default_mode_does_not_mark_command_tools_for_auto_approval(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL", "false")
    clear_settings_cache()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    assert tools["run_shell_command"].annotations is None


def test_oauth_dynamic_registration_authorize_token_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_BASE_URL", "https://local-shell-mcp.example.com"
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN", "1234")
    monkeypatch.delenv("LOCAL_SHELL_MCP_OAUTH_ISSUER", raising=False)
    monkeypatch.delenv("LOCAL_SHELL_MCP_OAUTH_RESOURCE", raising=False)
    clear_settings_cache()

    client = TestClient(wrap_http_app(Starlette()))
    register_response = client.post(
        "/oauth/register",
        json={
            "client_name": "Regression Client",
            "redirect_uris": ["https://client.example/callback"],
        },
    )

    assert register_response.status_code == 201
    assert register_response.headers["cache-control"] == "no-store"
    registration = register_response.json()
    assert registration["client_id"].startswith("local-shell-mcp-")
    assert registration["client_name"] == "Regression Client"
    assert registration["redirect_uris"] == ["https://client.example/callback"]

    verifier = "v" * 64
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    authorize_response = client.post(
        "/oauth/authorize",
        data={
            "response_type": "code",
            "client_id": registration["client_id"],
            "redirect_uri": "https://client.example/callback",
            "resource": "https://local-shell-mcp.example.com/mcp",
            "scope": "shell:read shell:execute",
            "state": "opaque-state",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "pin": "1234",
        },
        follow_redirects=False,
    )

    assert authorize_response.status_code == 302
    redirect = urlparse(authorize_response.headers["location"])
    assert f"{redirect.scheme}://{redirect.netloc}{redirect.path}" == (
        "https://client.example/callback"
    )
    redirect_query = parse_qs(redirect.query)
    assert redirect_query["iss"] == ["https://local-shell-mcp.example.com"]
    assert redirect_query["state"] == ["opaque-state"]
    code = redirect_query["code"][0]

    token_response = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": registration["client_id"],
            "redirect_uri": "https://client.example/callback",
            "resource": "https://local-shell-mcp.example.com/mcp",
            "code_verifier": verifier,
        },
    )

    assert token_response.status_code == 200
    assert token_response.headers["cache-control"] == "no-store"
    token_payload = token_response.json()
    assert token_payload["token_type"] == "Bearer"
    assert token_payload["scope"] == "shell:read shell:execute"
    assert token_payload["expires_in"] > 0

    claims = validate_bearer_token(token_payload["access_token"])
    assert claims["iss"] == "https://local-shell-mcp.example.com"
    assert claims["aud"] == "https://local-shell-mcp.example.com/mcp"
    assert claims["client_id"] == registration["client_id"]
    assert claims["scope"] == "shell:read shell:execute"

    reuse_response = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": registration["client_id"],
            "redirect_uri": "https://client.example/callback",
            "resource": "https://local-shell-mcp.example.com/mcp",
            "code_verifier": verifier,
        },
    )

    assert reuse_response.status_code == 400
    assert reuse_response.json() == {
        "error": "invalid_grant",
        "error_description": "Unknown or used code",
    }


def test_oauth_access_tokens_expire_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.delenv("LOCAL_SHELL_MCP_BASE_URL", raising=False)
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


def test_oauth_authorize_form_escapes_reflected_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()

    marker = chr(60) + "unsafe" + chr(62)
    response = _authorize_form(
        {
            "client_id": "client",
            "redirect_uri": f"https://example.test/cb?x={marker}",
            "resource": f"https://resource.test/{marker}",
            "scope": f"shell:read {marker}",
        },
        error=f"bad {marker}",
    )
    body = bytes(response.body).decode("utf-8")

    assert marker not in body
    assert "&lt;unsafe&gt;" in body
