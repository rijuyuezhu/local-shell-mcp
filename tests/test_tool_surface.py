import json
from typing import cast

import pytest
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError

import local_shell_mcp.server.http.tool_routes as http_tool_routes_module
from local_shell_mcp import __version__
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.remote.tool_specs import (
    REMOTE_WORKER_TOOL_NAMES,
    REMOTE_WORKER_TOOL_SPECS,
)
from local_shell_mcp.remote.worker import WORKER_TOOL_NAMES
from local_shell_mcp.server.http.app import build_http_app
from local_shell_mcp.server.mcp.app import build_mcp
from local_shell_mcp.tools.contracts import (
    HttpMethod,
    HttpToolRoute,
    ToolRegistry,
)
from local_shell_mcp.tools.declarative import (
    DeclarativeToolRegistry,
    _normalize_description,
)
from local_shell_mcp.tools.discovery import discover_tool_registries
from local_shell_mcp.tools.local_invocations import (
    UnknownLocalToolError,
    call_local_tool,
    local_tool_handlers,
)
from tests.helpers import mcp_text

LOCAL_MCP_TOOL_NAMES = {
    "bash",
    "read",
    "search",
    "workspace_search",
    "fetch",
    "session_start",
    "session_change_cwd",
    "version",
    "run_python_code",
    "send_persistent_shell_input",
    "read_persistent_shell_output",
    "kill_persistent_shell",
    "list_persistent_shells",
    "list_files",
    "tree_view",
    "glob_search",
    "write_file",
    "edit_lines",
    "delete_file_or_dir",
    "apply_patch",
    "create_file_link",
    "list_file_links",
    "revoke_file_link",
    "secret_scan",
    "read_todos",
    "write_todos",
    "job",
}


def test_normalize_description_cleans_docstring_text():
    assert _normalize_description(
        """
        First line with   extra   spaces.
          Continued line.

            Second paragraph
            with tabs	and spaces.

        """
    ) == (
        "First line with extra spaces. Continued line.\n\n"
        "Second paragraph with tabs and spaces."
    )


REMOTE_MCP_TOOL_NAMES = {
    "remote_admin",
}


@pytest.mark.asyncio
async def test_mcp_local_and_remote_tool_surface_is_stable(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODE", "mcp")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()
    local_tool_handlers.cache_clear()

    names = {tool.name for tool in await build_mcp().list_tools()}

    assert names == LOCAL_MCP_TOOL_NAMES | REMOTE_MCP_TOOL_NAMES


@pytest.mark.asyncio
async def test_stdio_mcp_hides_http_server_backed_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODE", "stdio")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()
    local_tool_handlers.cache_clear()

    names = {tool.name for tool in await build_mcp().list_tools()}

    assert names == LOCAL_MCP_TOOL_NAMES - {
        "create_file_link",
        "list_file_links",
        "revoke_file_link",
    }
    assert names.isdisjoint(REMOTE_MCP_TOOL_NAMES)


@pytest.mark.asyncio
async def test_remaining_stateful_tools_require_session_id(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    tools = {tool.name: tool for tool in await build_mcp().list_tools()}
    stateful_tool_names = {
        "list_files",
        "write_file",
        "delete_file_or_dir",
        "apply_patch",
        "create_file_link",
        "list_file_links",
        "revoke_file_link",
        "secret_scan",
        "read_todos",
        "write_todos",
    }

    for name in stateful_tool_names:
        assert "session_id" in tools[name].inputSchema["required"]

    assert "session_id" not in tools["workspace_search"].inputSchema["required"]
    assert "session_id" not in tools["fetch"].inputSchema["required"]


def test_remote_registry_declares_only_remote_admin(monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODE", "mcp")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    clear_settings_cache()
    local_tool_handlers.cache_clear()

    registry = cast(
        DeclarativeToolRegistry,
        next(
            registry
            for registry in discover_tool_registries()
            if registry.name == "remote"
        ),
    )
    names = {tool.name for tool in registry.tools}
    route_names = {route.tool_name for route in registry.http_routes()}
    handler_names = set(registry.http_handlers())
    legacy_names = {
        "remote_invite",
        "remote_list_machines",
        "remote_revoke_machine",
        "remote_rename_machine",
        "remote_copy_file",
        "remote_copy_dir",
        "remote_pull_file",
        "remote_push_file",
        "remote_pull_dir",
        "remote_push_dir",
    }

    assert names == {"remote_admin"}
    assert "remote_admin" in route_names
    assert "remote_admin" in handler_names
    assert "remote" not in route_names
    assert "remote" not in handler_names
    assert names.isdisjoint(legacy_names)
    assert route_names.isdisjoint(legacy_names)
    assert handler_names.isdisjoint(legacy_names)


def test_remote_worker_specs_drive_http_and_worker_allowlist(monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODE", "mcp")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    clear_settings_cache()
    local_tool_handlers.cache_clear()

    exposed_specs = [
        spec for spec in REMOTE_WORKER_TOOL_SPECS if spec.expose_http
    ]
    spec_names = {spec.public_name for spec in exposed_specs}
    worker_tools = {spec.worker_tool for spec in REMOTE_WORKER_TOOL_SPECS}
    route_by_name = {
        route.tool_name: route
        for registry in discover_tool_registries()
        for route in registry.http_routes()
    }
    handler_names = set(local_tool_handlers())

    assert len(spec_names) == len(exposed_specs)
    assert worker_tools == REMOTE_WORKER_TOOL_NAMES
    assert WORKER_TOOL_NAMES == REMOTE_WORKER_TOOL_NAMES
    assert spec_names <= set(route_by_name)
    assert spec_names <= handler_names
    for spec in exposed_specs:
        route = route_by_name[spec.public_name]
        assert route.method == "POST"
        assert route.path == spec.http_path


def test_http_openapi_version_matches_package_version(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    response = TestClient(build_http_app()).get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["version"] == __version__


def test_http_public_version_endpoint_reports_package_version(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    response = TestClient(build_http_app()).get("/version")

    assert response.status_code == 200
    assert response.json()["version"] == __version__
    assert response.json()["python"]


@pytest.mark.asyncio
async def test_http_version_matches_mcp_tool_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    http_payload = TestClient(build_http_app()).get("/tools/version").json()
    mcp_response = await build_mcp().call_tool("version", {})

    assert http_payload == _mcp_payload_data(mcp_response)
    assert http_payload["version"] == __version__


def _mcp_payload_data(response):
    return (
        response[1]
        if isinstance(response, tuple)
        else json.loads(mcp_text(response))
    )


@pytest.mark.asyncio
async def test_http_list_files_matches_mcp_tool_payload(tmp_path, monkeypatch):
    (tmp_path / "alpha.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    client = TestClient(build_http_app())
    session = client.post("/tools/session_start", json={"workdir": "."}).json()
    args = {"session_id": session["session_id"], "path": "."}
    http_payload = client.post("/tools/list_files", json=args).json()
    mcp_response = await build_mcp().call_tool("list_files", args)
    assert http_payload == _mcp_payload_data(mcp_response)


@pytest.mark.asyncio
async def test_http_read_todos_matches_mcp_tool_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    client = TestClient(build_http_app())
    session = client.post("/tools/session_start", json={"workdir": "."}).json()
    args = {"session_id": session["session_id"]}
    http_payload = client.get("/tools/todo", params=args).json()
    mcp_response = await build_mcp().call_tool("read_todos", args)

    assert http_payload == _mcp_payload_data(mcp_response)


@pytest.mark.asyncio
async def test_http_secret_scan_matches_mcp_tool_payload(tmp_path, monkeypatch):
    (tmp_path / "safe.txt").write_text("hello\n", encoding="utf-8")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    client = TestClient(build_http_app())
    session = client.post("/tools/session_start", json={"workdir": "."}).json()
    args = {"session_id": session["session_id"], "cwd": ".", "max_results": 10}
    http_payload = client.post("/tools/secret_scan", json=args).json()
    mcp_response = await build_mcp().call_tool("secret_scan", args)

    assert http_payload == _mcp_payload_data(mcp_response)


def test_http_tool_name_is_not_request_overridable(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    client = TestClient(build_http_app())
    session = client.post("/tools/session_start", json={"workdir": "."}).json()
    response = client.get(
        "/tools/todo",
        params={
            "session_id": session["session_id"],
            "tool_name": "list_persistent_shells",
        },
    )

    assert response.status_code == 200
    assert "todos" in response.json()


def test_http_tool_missing_required_arg_returns_validation_error(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    client = TestClient(build_http_app())
    for path, payload in (
        ("/tools/read", {}),
        ("/tools/bash", {"command": "echo ok"}),
        ("/tools/job", {}),
    ):
        response = client.post(path, json=payload)

        assert response.status_code == 400
        assert response.json() == {
            "error": "validation_error",
            "message": "Missing required argument: session_id",
        }


def test_todos_are_session_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()
    from local_shell_mcp.ops.todo import read_todos_execute, write_todos_execute
    from local_shell_mcp.tool_session.store import get_tool_session_store

    store = get_tool_session_store()
    store.clear()
    first = store.create_session(workdir=".").session_id
    second = store.create_session(workdir=".").session_id
    first_items = [{"id": "first", "content": "one"}]
    second_items = [{"id": "second", "content": "two"}]

    write_todos_execute(first_items, first)
    write_todos_execute(second_items, second)

    assert read_todos_execute(first).todos[0].id == "first"
    assert read_todos_execute(first).todos[0].content == "one"
    assert read_todos_execute(second).todos[0].id == "second"
    assert read_todos_execute(second).todos[0].content == "two"


def test_http_tool_file_not_found_returns_json_error(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    client = TestClient(build_http_app())
    session = client.post("/tools/session_start", json={"workdir": "."}).json()
    response = client.post(
        "/tools/read",
        json={"session_id": session["session_id"], "path": "missing.txt"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": "FileNotFoundError",
        "message": f"FileNotFoundError: {tmp_path / 'missing.txt'}",
    }


def test_http_tool_unexpected_error_returns_json_error(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    async def broken_call_local_tool(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        http_tool_routes_module, "call_local_tool", broken_call_local_tool
    )

    response = TestClient(build_http_app(), raise_server_exceptions=False).post(
        "/tools/read", json={"path": "a.txt"}
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": "internal_error",
        "message": "Unhandled RuntimeError: boom",
    }


def test_http_mode_hides_remote_worker_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODE", "http")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()
    local_tool_handlers.cache_clear()

    response = TestClient(build_http_app()).post(
        "/tools/run_remote_shell_command", json={"command": "echo ok"}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.asyncio
async def test_mcp_tool_missing_required_arg_uses_fastmcp_tool_error(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    with pytest.raises(ToolError, match="validation errors for readArguments"):
        await build_mcp().call_tool("read", {})


@pytest.mark.asyncio
async def test_mcp_remote_facade_is_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    tools = {tool.name for tool in await build_mcp().list_tools()}
    assert "remote" not in tools

    with pytest.raises(ToolError, match="Unknown tool: remote"):
        await build_mcp().call_tool(
            "remote",
            {
                "machine": "worker-a",
                "op": "bash",
                "args": {"command": "echo ok"},
            },
        )


@pytest.mark.asyncio
async def test_mcp_unknown_tool_uses_fastmcp_tool_error(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    with pytest.raises(ToolError, match="Unknown tool: no_such_tool"):
        await build_mcp().call_tool("no_such_tool", {})


def test_http_tool_routes_reject_unsupported_methods(monkeypatch):
    class RegistryWithUnsupportedRoute:
        def http_routes(self):
            return [
                HttpToolRoute(
                    cast(HttpMethod, "PUT"), "/tools/example", "read_todos"
                )
            ]

    monkeypatch.setattr(
        "local_shell_mcp.server.http.tool_routes.discover_tool_registries",
        lambda: [RegistryWithUnsupportedRoute()],
    )

    with pytest.raises(ValueError, match="Unsupported HTTP tool method 'PUT'"):
        build_http_app()


@pytest.mark.asyncio
async def test_local_invocations_report_unknown_tool(monkeypatch):
    class EmptyRegistry(ToolRegistry):
        pass

    monkeypatch.setattr(
        "local_shell_mcp.tools.local_invocations.discover_tool_registries",
        lambda: [EmptyRegistry()],
    )
    local_tool_handlers.cache_clear()

    try:
        with pytest.raises(
            UnknownLocalToolError, match="Unknown local tool: example_tool"
        ):
            await call_local_tool("example_tool", {})
    finally:
        local_tool_handlers.cache_clear()


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
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "agents"))
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

        internal_worker_handlers = REMOTE_WORKER_TOOL_NAMES - {
            spec.worker_tool
            for spec in REMOTE_WORKER_TOOL_SPECS
            if spec.expose_http
        }

        assert route_tool_names == mcp_tool_names
        assert handler_tool_names == mcp_tool_names | internal_worker_handlers
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

    session = await call_local_tool("session_start", {"workdir": "."})
    payload = await call_local_tool(
        "apply_patch",
        {"session_id": session.session_id, "patch": patch, "cwd": "."},
    )

    assert payload.ok is True
    assert (tmp_path / "target.txt").read_text(encoding="utf-8") == "new\n"


@pytest.mark.asyncio
async def test_run_python_code_creates_temp_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    payload = await call_local_tool(
        "run_python_code", {"code": "print('py314')", "cwd": "."}
    )

    assert payload.ok is True
    assert payload.stdout == "py314\n"
