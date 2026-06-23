import pytest

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.server.mcp.app import build_mcp
from tests.helpers import mcp_structured


@pytest.mark.asyncio
async def test_read_facade_reads_line_selector_with_numbered_content(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()
    (tmp_path / "demo.py").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    response = await build_mcp().call_tool("read", {"path": "demo.py:2-3"})
    result = mcp_structured(response)

    assert result["kind"] == "file"
    assert result["content"] == "2|beta\n3|gamma"
    assert result["file"]["content"] == "beta\ngamma"
    assert result["file"]["start_line"] == 2
    assert result["file"]["seen_ranges"] == [{"start": 2, "end": 3}]


@pytest.mark.asyncio
async def test_read_facade_raw_selector_returns_unnumbered_content(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()
    (tmp_path / "demo.py").write_text("alpha\nbeta\n", encoding="utf-8")

    response = await build_mcp().call_tool("read", {"path": "demo.py:raw"})
    result = mcp_structured(response)

    assert result["kind"] == "file"
    assert result["raw"] is True
    assert result["content"] == "alpha\nbeta\n"
    assert result["file"]["numbered_content"] == "1|alpha\n2|beta"


@pytest.mark.asyncio
async def test_read_facade_lists_directories(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "demo.py").write_text("", encoding="utf-8")

    response = await build_mcp().call_tool("read", {"path": "pkg"})
    result = mcp_structured(response)

    assert result["kind"] == "directory"
    assert "file\tpkg/demo.py" in result["content"]
    assert result["directory"]["count"] == 1
