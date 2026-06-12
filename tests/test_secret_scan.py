import pytest

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.ops.fs_ops import write_text
from local_shell_mcp.ops.secret_scan_ops import run_secret_scan


@pytest.mark.asyncio
async def testsecret_scan(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    write_text("x.py", "TOKEN = 'ghp_1234567890123456789012345678901234567890'")
    result = await run_secret_scan(".")
    assert result["findings"]
