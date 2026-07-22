"""Regression tests for non-enumerated deprecated MCP tool tombstones."""

from __future__ import annotations

from local_shell_mcp.deprecated_tools import (
    DEPRECATED_TOOL_HELP_URL,
    DeprecatedToolFastMCP,
)
from local_shell_mcp.server.mcp.app import build_mcp


async def test_deprecated_tools_are_tombstones_not_listed_tools() -> None:
    mcp = DeprecatedToolFastMCP("test")

    @mcp.tool()
    def current_tool() -> str:
        return "current"

    listed = {tool.name for tool in await mcp.list_tools()}
    assert listed == {"current_tool"}
    assert "version_info" not in listed

    result = await mcp.call_tool("version_info", {})
    assert result["ok"] is False
    assert result["data"] == {
        "status": "stale_tool_snapshot",
        "deprecated_tool": "version_info",
        "replacement": "version",
        "removed_in": "3.0.0",
        "help_url": DEPRECATED_TOOL_HELP_URL,
        "assistant_instruction": (
            "Do not retry this deprecated tool. Explain that the MCP client is using "
            "a stale local-shell-mcp tool snapshot and ask the user to refresh the App's "
            "tools, or remove and re-add the App when refresh is unavailable. After the "
            "snapshot is updated, use 'version'."
        ),
    }

    current = await mcp.call_tool("current_tool", {})
    assert current


async def test_build_mcp_installs_tombstones_without_enumerating_them(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")

    from local_shell_mcp.config.settings import clear_settings_cache

    clear_settings_cache()
    mcp = build_mcp()

    listed = {tool.name for tool in await mcp.list_tools()}
    assert "version" in listed
    assert "remote_run_shell_tool" not in listed

    result = await mcp.call_tool("remote_run_shell_tool", {"machine": "worker"})
    assert isinstance(result, dict)
    data = result["data"]
    assert isinstance(data, dict)
    assert data["status"] == "stale_tool_snapshot"
    assert data["replacement"] == "bash"
    assert "session_start(target='remote'" in data["assistant_instruction"]
