import json

import pytest
from fastapi.testclient import TestClient

from local_shell_mcp.config.settings import get_settings
from local_shell_mcp.http_app import build_http_app
from local_shell_mcp.tools import build_mcp

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
    "git_clone_tool",
    "git_status_tool",
    "git_diff_tool",
    "git_log_tool",
    "git_checkout_tool",
    "git_fetch_tool",
    "git_pull_tool",
    "git_add_tool",
    "git_commit_tool",
    "git_push_tool",
    "git_show_tool",
    "git_reset_tool",
    "secret_scan",
    "todo_read_tool",
    "todo_write_tool",
    "audit_tail",
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
    "remote_git_clone_tool",
    "remote_git_status_tool",
    "remote_git_diff_tool",
    "remote_git_log_tool",
    "remote_git_checkout_tool",
    "remote_git_fetch_tool",
    "remote_git_pull_tool",
    "remote_git_add_tool",
    "remote_git_commit_tool",
    "remote_git_push_tool",
    "remote_git_show_tool",
    "remote_git_reset_tool",
}


@pytest.mark.asyncio
async def test_mcp_local_and_remote_tool_surface_is_stable(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    get_settings.cache_clear()

    names = {tool.name for tool in await build_mcp().list_tools()}

    assert names == LOCAL_MCP_TOOL_NAMES | REMOTE_MCP_TOOL_NAMES


@pytest.mark.asyncio
async def test_http_list_files_matches_mcp_tool_payload(tmp_path, monkeypatch):
    (tmp_path / "alpha.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    get_settings.cache_clear()

    http_payload = (
        TestClient(build_http_app())
        .post("/tools/list_files", json={"path": "."})
        .json()
    )
    mcp_response = await build_mcp().call_tool("list_files", {"path": "."})
    mcp_payload = json.loads(mcp_response[0].text)

    assert http_payload == mcp_payload["data"]


@pytest.mark.asyncio
async def test_http_git_status_matches_mcp_tool_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    get_settings.cache_clear()

    TestClient(build_http_app()).post(
        "/tools/run_shell", json={"command": "git init"}
    )
    http_payload = (
        TestClient(build_http_app())
        .post("/tools/git/status", json={"cwd": "."})
        .json()
    )
    mcp_response = await build_mcp().call_tool("git_status_tool", {"cwd": "."})
    mcp_payload = json.loads(mcp_response[0].text)["data"]

    assert {k: v for k, v in http_payload.items() if k != "duration_ms"} == {
        k: v for k, v in mcp_payload.items() if k != "duration_ms"
    }
