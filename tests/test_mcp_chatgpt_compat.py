import base64
import hashlib
import json
import re
import time
from typing import Any
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
from local_shell_mcp.oauth.urls import _scopes, resource_url
from local_shell_mcp.server.mcp.app import (
    _transport_security_settings,
    build_mcp,
)
from local_shell_mcp.tools.registry import agent as tools_module
from tests.helpers import mcp_structured


def _output_schema(tool: Any) -> dict[str, Any]:
    schema = tool.outputSchema
    assert schema is not None
    return schema


def test_oauth_supported_scopes_include_feature_scopes():
    assert _scopes() == [
        "shell:read",
        "shell:write",
        "shell:execute",
        "git:write",
        "file:share",
        "remote:use",
    ]


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
    assert "You are a coding agent aiming to help the user" in mcp.instructions
    assert "Do not commit, push, amend, create PRs, release" in mcp.instructions
    assert "secret_scan is heuristic" in mcp.instructions
    assert (
        "`session_id` identifies the agent/workspace session"
        in mcp.instructions
    )
    assert "`bash(async_=true)` returns a `job_id`" in mcp.instructions
    assert "`bash(pty=true)` is local-session only" in mcp.instructions
    assert "Do not use `shell_id` with `job`" in mcp.instructions

    transport_security = mcp.settings.transport_security
    assert transport_security is not None
    assert "local-shell-mcp.example.com" in transport_security.allowed_hosts
    assert "local-shell-mcp.example.com:443" in transport_security.allowed_hosts
    assert (
        "local-shell-mcp.example.com:*" not in transport_security.allowed_hosts
    )

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    search_meta = tools["workspace_search"].meta
    session_meta = tools["session_start"].meta
    assert "environment_info" not in tools
    assert "remote" not in tools
    assert search_meta is not None
    assert session_meta is not None
    assert search_meta["securitySchemes"][0]["type"] == "noauth"
    assert search_meta["securitySchemes"][1]["scopes"] == ["shell:read"]
    assert session_meta["securitySchemes"][0]["type"] == "oauth2"
    assert session_meta["securitySchemes"][0]["scopes"] == ["shell:read"]

    def tool_oauth_scopes(name: str) -> list[str]:
        meta = tools[name].meta
        assert meta is not None
        return meta["securitySchemes"][0]["scopes"]

    assert tool_oauth_scopes("bash") == [
        "shell:read",
        "shell:execute",
    ]
    assert tool_oauth_scopes("write_file") == [
        "shell:read",
        "shell:write",
    ]
    assert tool_oauth_scopes("create_file_link") == [
        "shell:read",
        "file:share",
    ]
    assert tool_oauth_scopes("remote_admin") == ["remote:use"]
    assert all(tool.outputSchema is not None for tool in tools.values())
    bash_schema = tools["bash"].outputSchema
    assert bash_schema is not None
    assert bash_schema["title"] == "ShellExecutionOutput"
    assert set(bash_schema["properties"]) >= {
        "mode",
        "command",
        "cwd",
        "result",
    }
    assert "session_id" in tools["bash"].inputSchema["required"]
    assert "session_id" in tools["run_python_code"].inputSchema["required"]
    assert "session_id" in tools["tree_view"].inputSchema["required"]
    assert "session_id" in tools["glob_search"].inputSchema["required"]
    assert "session_id" in tools["job"].inputSchema["required"]
    search_schema = tools["search"].outputSchema
    assert search_schema is not None
    assert "matches" in search_schema["properties"]
    assert "numbered_content" in search_schema["properties"]
    fetch_schema = tools["fetch"].outputSchema
    assert fetch_schema is not None
    assert set(fetch_schema["properties"]) == {
        "id",
        "title",
        "text",
        "url",
        "metadata",
    }
    assert "search -> fetch workflow" in (
        tools["workspace_search"].description or ""
    )
    assert "id should normally come from a prior workspace_search" in (
        tools["fetch"].description or ""
    )
    assert "prefer read(session_id, path)" in (tools["fetch"].description or "")

    structured = mcp_structured(
        await mcp.call_tool("session_start", {"workdir": "."})
    )
    assert re.fullmatch(r"[A-Za-z0-9]{8}", structured["session_id"])
    assert structured["target"] == "local"
    assert structured["workdir"] == str(tmp_path)
    assert structured["workspace_root"] == str(tmp_path)
    assert (
        structured["message"]
        == "Use this session_id in subsequent workspace tool calls."
    )


@pytest.mark.asyncio
async def test_shell_tool_input_and_output_schema_descriptions_are_exposed(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    tool = {tool.name: tool for tool in await build_mcp().list_tools()}["bash"]

    output_schema = _output_schema(tool)
    command_input = tool.inputSchema["properties"]["command"]
    session_input = tool.inputSchema["properties"]["session_id"]
    timeout_input = tool.inputSchema["properties"]["timeout_s"]
    mode_output = output_schema["properties"]["mode"]
    result_output = output_schema["properties"]["result"]

    assert "terminal work" in command_input["description"]
    assert "agent/workspace session_id" in session_input["description"]
    assert "session_id" in tool.inputSchema["required"]
    assert "bounded command mode" in timeout_input["description"]
    assert "Execution mode" in mode_output["description"]
    assert "bounded command" in result_output["description"]
    description = tool.description or ""
    assert "session_id returned by session_start" in description
    assert "job_id owned by the same session_id" in description
    assert "shell_id for persistent-shell companion tools" in description
    assert "Do not use shell_id with job" in description


@pytest.mark.asyncio
async def test_persistent_shell_tools_use_shell_id_not_session_id(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}
    companion_names = [
        "send_persistent_shell_input",
        "read_persistent_shell_output",
        "kill_persistent_shell",
    ]
    for name in companion_names:
        tool = tools[name]
        input_properties = tool.inputSchema["properties"]
        input_text = str(tool.inputSchema) + (tool.description or "")
        output_schema = _output_schema(tool)
        output_text = str(output_schema)

        assert "shell_id" in tool.inputSchema["required"]
        assert "shell_id" in input_properties
        assert "session_id" not in input_properties
        assert "shell_id is separate" in input_text
        assert "agent/workspace session_id" in input_text
        assert "shell_id" in output_schema["properties"]
        assert "session_id" not in output_schema["properties"]
        assert "session_id" not in output_text

    list_schema = _output_schema(tools["list_persistent_shells"])
    assert "shells" in list_schema["properties"]
    assert "sessions" not in list_schema["properties"]
    assert "shell_id" in str(list_schema)
    assert "session_id" not in str(list_schema)


@pytest.mark.asyncio
async def test_shell_tool_returns_per_tool_structured_content(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    mcp = build_mcp()
    session = mcp_structured(
        await mcp.call_tool("session_start", {"workdir": "."})
    )
    structured = mcp_structured(
        await mcp.call_tool(
            "bash",
            {"session_id": session["session_id"], "command": "echo ok"},
        )
    )

    assert structured["mode"] == "command"
    assert structured["command"] == "echo ok"
    assert structured["result"]["stdout"] == "ok\n"
    assert "data" not in structured


@pytest.mark.asyncio
async def test_file_tool_input_and_output_schema_descriptions_are_exposed(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}
    read_tool = tools["read"]
    list_files_tool = tools["list_files"]

    read_output_schema = _output_schema(read_tool)
    list_files_output_schema = _output_schema(list_files_tool)
    assert read_output_schema["title"] == "ReadOutput"
    assert list_files_output_schema["title"] == "ListFilesOutput"
    assert (
        "selector suffix"
        in read_tool.inputSchema["properties"]["path"]["description"]
    )
    assert "binary_preview" not in read_tool.inputSchema["properties"]
    assert "binary_preview_bytes" not in read_tool.inputSchema["properties"]
    assert "file" in read_output_schema["properties"]
    assert "directory" in read_output_schema["properties"]
    assert (
        read_output_schema["properties"]["content"]["description"]
        == "Model-facing content. File reads use hashline-style text unless raw is true; directories use a compact listing."
    )
    assert (
        list_files_output_schema["properties"]["entries"]["description"]
        == "Returned directory entries."
    )


@pytest.mark.asyncio
async def test_search_tool_input_and_output_schema_descriptions_are_exposed(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}
    search_tool = tools["search"]
    tree_tool = tools["tree_view"]
    glob_tool = tools["glob_search"]

    search_output_schema = _output_schema(search_tool)
    tree_output_schema = _output_schema(tree_tool)
    assert search_output_schema["title"] == "GrepSearchOutput"
    assert tree_output_schema["title"] == "TreeViewOutput"
    assert search_tool.inputSchema["properties"]["pattern"]["description"] == (
        "Text or regular expression pattern to search for; prefer built-in search tools so matches carry grounding metadata."
    )
    assert (
        "case-sensitive"
        in search_tool.inputSchema["properties"]["case_sensitive"][
            "description"
        ]
    )
    assert (
        "line-scoped file selector"
        in search_tool.inputSchema["properties"]["paths"]["description"]
    )
    assert (
        "page through noisy searches"
        in search_tool.inputSchema["properties"]["skip"]["description"]
    )
    assert (
        search_output_schema["properties"]["matches"]["description"]
        == "Returned ripgrep matches."
    )
    assert (
        search_output_schema["properties"]["skipped"]["description"]
        == "Number of earlier matches skipped before the returned page."
    )
    assert "session_id" in tree_tool.inputSchema["required"]
    assert "session_id" in glob_tool.inputSchema["required"]
    assert (
        "session workdir"
        in tree_tool.inputSchema["properties"]["cwd"]["description"]
    )
    assert (
        "session workdir"
        in glob_tool.inputSchema["properties"]["cwd"]["description"]
    )
    assert "session_id returned by session_start" in (
        tree_tool.description or ""
    )
    assert "session_id returned by session_start" in (
        glob_tool.description or ""
    )
    assert (
        tree_output_schema["properties"]["entries"]["description"]
        == "Indented tree entries relative to root."
    )


@pytest.mark.asyncio
async def test_misc_tool_input_and_output_schema_descriptions_are_exposed(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}
    todo_tool = tools["write_todos"]
    secret_tool = tools["secret_scan"]

    todo_output_schema = _output_schema(todo_tool)
    secret_output_schema = _output_schema(secret_tool)
    assert todo_output_schema["title"] == "WriteTodosOutput"
    assert secret_output_schema["title"] == "SecretScanOutput"
    assert (
        "Replacement todo list"
        in todo_tool.inputSchema["properties"]["todos"]["description"]
    )
    assert (
        secret_output_schema["properties"]["findings"]["description"]
        == "Returned heuristic secret findings."
    )


@pytest.mark.asyncio
async def test_job_tool_schema_descriptions_explain_bash_companion(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}
    companion = tools["job"]
    description = companion.description or ""
    assert "bash" in description
    assert "Starting work belongs" in description

    lines_schema = companion.inputSchema["properties"]["lines"]
    assert lines_schema["minimum"] == 1
    assert lines_schema["maximum"] == 5000
    assert (
        "Output is available only while the background job can still be inspected"
        in lines_schema["description"]
    )
    assert "session_id" in companion.inputSchema["required"]
    assert (
        "Tracked bash"
        in companion.inputSchema["properties"]["cancel"]["description"]
    )

    output_schema = _output_schema(companion)
    assert output_schema["title"] == "JobOutput"
    assert output_schema["$defs"]["JobStatus"]["enum"] == [
        "running",
        "exited",
        "stopped",
        "lost",
        "unknown",
    ]
    job_info_schema = output_schema["$defs"]["JobInfo"]
    assert "backend" not in job_info_schema["properties"]
    assert (
        job_info_schema["properties"]["session_id"]["description"]
        == "Agent/workspace session_id that owns this tracked job."
    )
    assert (
        output_schema["properties"]["operation"]["description"]
        == "Job operation performed by the unified job companion tool."
    )


@pytest.mark.asyncio
async def test_tool_descriptions_include_runtime_limits(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_OUTPUT_BYTES", "12345")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_GREP_RESULTS", "678")
    clear_settings_cache()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}

    bash_description = tools["bash"].description or ""
    search_description = tools["search"].description or ""
    assert "timeout default/cap" in bash_description
    assert "max_grep_results=678" in search_description


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

    annotations = tools["bash"].annotations
    search_annotations = tools["workspace_search"].annotations
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

    run_shell_command_annotations = tools["bash"].annotations
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

    annotations = tools["bash"].annotations
    assert annotations is not None
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is False
    assert annotations.openWorldHint is False
    assert tools["bash"].meta == {
        "securitySchemes": [
            {
                "type": "oauth2",
                "scopes": ["shell:read", "shell:execute"],
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

    assert tools["bash"].annotations is None


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
