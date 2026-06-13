import pytest

from local_shell_mcp.config.settings import clear_settings_cache


@pytest.fixture(autouse=True)
def isolated_runtime_paths(monkeypatch, tmp_path):
    state_dir = tmp_path / ".local-shell-mcp"
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state_dir))
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(state_dir / "audit.jsonl")
    )
    clear_settings_cache()
    yield
    clear_settings_cache()
