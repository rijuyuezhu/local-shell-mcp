import pytest

from local_shell_mcp.fs_ops import write_text
from local_shell_mcp.settings import get_settings
from local_shell_mcp.tools import _is_placeholder_secret_match, _secret_scan


@pytest.mark.asyncio
async def test_secret_scan(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    fake_token = "gh" + "p_" + "1234567890123456789012345678901234567890"
    write_text("x.py", f"TOKEN = '{fake_token}'")
    result = await _secret_scan(".")
    assert result["findings"]


@pytest.mark.asyncio
async def test_secret_scan_respects_gitignore(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    write_text(".gitignore", "ignored.txt\n")
    ignored_token = "gh" + "p_" + "1234567890123456789012345678901234567890"
    visible_token = "gh" + "p_" + "abcdefghijklmnopqrstuvwxy1234567890123"
    write_text("ignored.txt", f"TOKEN = '{ignored_token}'")
    write_text("visible.txt", f"TOKEN = '{visible_token}'")

    result = await _secret_scan(".")

    paths = {item["path"] for item in result["findings"]}
    assert "visible.txt" in paths
    assert "ignored.txt" not in paths


def test_secret_scan_ignores_obvious_placeholder_assignments():
    assert _is_placeholder_secret_match("generic_assignment", "SECRET = '${EXAMPLE:-dev-change-me}'")
    assert _is_placeholder_secret_match("generic_assignment", "OAUTH_SECRET = 'ci-local-shell-mcp-secret-fixture'")
    assert not _is_placeholder_secret_match("generic_assignment", "SECRET = 'realistic-live-value-123'")
