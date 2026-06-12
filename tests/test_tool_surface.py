import json
from typing import cast

import pytest
from fastapi.testclient import TestClient

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.http.app import build_http_app
from local_shell_mcp.mcp.app import build_mcp
from local_shell_mcp.remote.tool_specs import (
    REMOTE_WORKER_TOOL_NAMES,
    REMOTE_WORKER_TOOL_SPECS,
)
from local_shell_mcp.remote.worker import WORKER_TOOL_NAMES
from local_shell_mcp.tools.base import HttpMethod, HttpToolRoute, ToolRegistry
from local_shell_mcp.tools.discovery import discover_tool_registries
from local_shell_mcp.tools.local_invocations import (
    call_local_tool,
    local_tool_handlers,
)
from tests.helpers import mcp_text

LOCAL_MCP_TOOL_NAMES = {
    "search",
    "fetch",
    "environment_info",
    "run_shell_tool",
    "run_python_tool",
    "shell_start",
    "shell_send",
    "shell_read",
    "shell_kill",
    "shell_list",
    "list_files",
    "tree_view",
    "glob_search",
    "grep_search",
    "read_file",
    "read_many_files",
    "write_file",
    "edit_file",
    "multi_edit_file",
    "delete_file_or_dir",
    "apply_patch",
    "secret_scan",
    "todo_read_tool",
    "todo_write_tool",
}


REMOTE_MCP_TOOL_NAMES = {
    "remote_invite",
    "remote_list_machines",
    "remote_revoke_machine",
    "remote_rename_machine",
    "remote_environment_info",
    "remote_run_shell_tool",
    "remote_run_python_tool",
    "remote_shell_start",
    "remote_shell_send",
    "remote_shell_read",
    "remote_shell_kill",
    "remote_shell_list",
    "remote_list_files",
    "remote_tree_view",
    "remote_glob_search",
    "remote_grep_search",
    "remote_read_file",
    "remote_read_many_files",
    "remote_write_file",
    "remote_edit_file",
    "remote_multi_edit_file",
    "remote_delete_file_or_dir",
    "remote_apply_patch",
}


@pytest.mark.asyncio
async def test_mcp_local_and_remote_tool_surface_is_stable(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    names = {tool.name for tool in await build_mcp().list_tools()}

    assert names == LOCAL_MCP_TOOL_NAMES | REMOTE_MCP_TOOL_NAMES


def test_remote_worker_specs_drive_http_and_worker_allowlist():
    spec_names = {spec.public_name for spec in REMOTE_WORKER_TOOL_SPECS}
    worker_tools = {spec.worker_tool for spec in REMOTE_WORKER_TOOL_SPECS}
    route_by_name = {
        route.tool_name: route
        for registry in discover_tool_registries()
        for route in registry.http_routes()
    }
    handler_names = set(local_tool_handlers())

    assert len(spec_names) == len(REMOTE_WORKER_TOOL_SPECS)
    assert worker_tools == REMOTE_WORKER_TOOL_NAMES
    assert WORKER_TOOL_NAMES == REMOTE_WORKER_TOOL_NAMES
    assert spec_names <= set(route_by_name)
    assert spec_names <= handler_names
    for spec in REMOTE_WORKER_TOOL_SPECS:
        route = route_by_name[spec.public_name]
        assert route.method == "POST"
        assert route.path == spec.http_path


def _mcp_payload_data(response):
    return json.loads(mcp_text(response))["data"]


@pytest.mark.asyncio
async def test_http_list_files_matches_mcp_tool_payload(tmp_path, monkeypatch):
    (tmp_path / "alpha.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    http_payload = (
        TestClient(build_http_app())
        .post("/tools/list_files", json={"path": "."})
        .json()
    )
    mcp_response = await build_mcp().call_tool("list_files", {"path": "."})
    assert http_payload == _mcp_payload_data(mcp_response)


@pytest.mark.asyncio
async def test_http_todo_read_matches_mcp_tool_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    http_payload = TestClient(build_http_app()).get("/tools/todo").json()
    mcp_response = await build_mcp().call_tool("todo_read_tool", {})

    assert http_payload == _mcp_payload_data(mcp_response)


@pytest.mark.asyncio
async def test_http_secret_scan_matches_mcp_tool_payload(tmp_path, monkeypatch):
    (tmp_path / "safe.txt").write_text("hello\n", encoding="utf-8")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    args = {"cwd": ".", "max_results": 10}
    http_payload = (
        TestClient(build_http_app())
        .post("/tools/secret_scan", json=args)
        .json()
    )
    mcp_response = await build_mcp().call_tool("secret_scan", args)

    assert http_payload == _mcp_payload_data(mcp_response)


def test_http_tool_name_is_not_request_overridable(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    response = TestClient(build_http_app()).get(
        "/tools/todo", params={"tool_name": "shell_list"}
    )

    assert response.status_code == 200
    assert "todos" in response.json()


def test_http_tool_routes_reject_unsupported_methods(monkeypatch):
    class RegistryWithUnsupportedRoute:
        def http_routes(self):
            return [
                HttpToolRoute(
                    cast(HttpMethod, "PUT"), "/tools/example", "todo_read_tool"
                )
            ]

    monkeypatch.setattr(
        "local_shell_mcp.http.app.discover_tool_registries",
        lambda: [RegistryWithUnsupportedRoute()],
    )

    with pytest.raises(ValueError, match="Unsupported HTTP tool method 'PUT'"):
        build_http_app()


@pytest.mark.asyncio
async def test_local_invocations_are_collected_from_discovered_registries(
    monkeypatch,
):
    async def example_handler(args):
        return {"from_registry": args["value"]}

    class ExampleRegistry(ToolRegistry):
        def http_handlers(self):
            return {"example_tool": example_handler}

    monkeypatch.setattr(
        "local_shell_mcp.tools.local_invocations.discover_tool_registries",
        lambda: [ExampleRegistry()],
    )
    local_tool_handlers.cache_clear()

    try:
        assert await call_local_tool("example_tool", {"value": 42}) == {
            "from_registry": 42
        }
    finally:
        local_tool_handlers.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_bridge_enabled", ["false", "true"])
async def test_mcp_tools_have_matching_http_routes_and_handlers(
    tmp_path, monkeypatch, agent_bridge_enabled
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(tmp_path / "agents")
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", agent_bridge_enabled
    )
    clear_settings_cache()
    local_tool_handlers.cache_clear()

    try:
        mcp_tool_names = {tool.name for tool in await build_mcp().list_tools()}
        route_tool_names = {
            route.tool_name
            for registry in discover_tool_registries()
            for route in registry.http_routes()
        }
        handler_tool_names = set(local_tool_handlers())

        assert route_tool_names == mcp_tool_names
        assert handler_tool_names == mcp_tool_names
    finally:
        local_tool_handlers.cache_clear()


@pytest.mark.asyncio
async def test_apply_patch_tool_creates_temp_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()
    (tmp_path / "target.txt").write_text("old\n", encoding="utf-8")

    patch = """diff --git a/target.txt b/target.txt
--- a/target.txt
+++ b/target.txt
@@ -1 +1 @@
-old
+new
"""

    payload = await call_local_tool("apply_patch", {"patch": patch, "cwd": "."})

    assert payload["ok"] is True
    assert (tmp_path / "target.txt").read_text(encoding="utf-8") == "new\n"


@pytest.mark.asyncio
async def test_run_python_tool_creates_temp_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    payload = await call_local_tool(
        "run_python_tool", {"code": "print('py314')", "cwd": "."}
    )

    assert payload["ok"] is True
    assert payload["stdout"] == "py314\n"
