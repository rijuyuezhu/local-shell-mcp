import json
from typing import cast

import pytest
from fastapi.testclient import TestClient

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.http_app import build_http_app
from local_shell_mcp.mcp_app import build_mcp
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
    mcp_payload = json.loads(mcp_text(mcp_response))

    assert http_payload == mcp_payload["data"]


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
        "local_shell_mcp.http_app.discover_tool_registries",
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


def test_discovered_http_routes_have_registry_handlers():
    route_tool_names = {
        route.tool_name
        for registry in discover_tool_registries()
        for route in registry.http_routes()
    }

    assert route_tool_names <= set(local_tool_handlers())


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
