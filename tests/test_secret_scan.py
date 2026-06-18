import pytest

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.ops.files_ops import write_file_execute
from local_shell_mcp.ops.secret_scan_ops import secret_scan_execute


@pytest.mark.asyncio
async def testsecret_scan(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    write_file_execute(
        "x.py", "TOKEN = 'ghp_1234567890123456789012345678901234567890'"
    )
    result = await secret_scan_execute(".")
    assert result.findings
