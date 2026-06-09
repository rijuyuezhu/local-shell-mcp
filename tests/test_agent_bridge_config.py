import json

from local_shell_mcp.agent_bridge import (
    AgentBridgeManifest,
    load_agent_manifest,
    redact_mapping,
)
from local_shell_mcp.settings import get_settings


def test_agent_config_dir_defaults_to_home_agent(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.delenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert str(settings.agent_config_dir) == "/home/agent/local-shell-mcp-config"
    assert settings.agent_bridge_enabled is True
    assert settings.agent_mcp_probe_timeout_s == 5


def test_agent_config_dir_env_override(monkeypatch, tmp_path):
    config_dir = tmp_path / "agent-config"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    assert get_settings().agent_config_dir == config_dir.resolve()


def test_load_agent_manifest_missing_config(tmp_path):
    manifest = load_agent_manifest(tmp_path)

    assert manifest.status == "missing_config"
    assert manifest.config_path == tmp_path / "config.json"
    assert manifest.data == AgentBridgeManifest()
    assert manifest.errors == []


def test_load_agent_manifest_valid_config(tmp_path):
    config = {
        "version": 1,
        "mcpServers": {
            "github": {
                "type": "stdio",
                "command": "github-mcp-server",
                "args": ["stdio"],
                "env": {"GITHUB_TOKEN": "secret"},
            },
            "docs": {
                "type": "http",
                "url": "https://example.com/mcp",
                "headers": {"Authorization": "Bearer secret"},
                "enabled": False,
            },
        },
        "skills": {"enabled": True, "directory": "skills"},
        "dynamicTools": {"mcp": False, "skills": True},
    }
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")

    manifest = load_agent_manifest(tmp_path)

    assert manifest.status == "loaded"
    assert manifest.data.mcp_servers["github"].command == "github-mcp-server"
    assert manifest.data.mcp_servers["docs"].enabled is False
    assert manifest.data.dynamic_tools.mcp is False
    assert manifest.data.skills.directory == "skills"


def test_load_agent_manifest_invalid_json(tmp_path):
    (tmp_path / "config.json").write_text("{not-json", encoding="utf-8")

    manifest = load_agent_manifest(tmp_path)

    assert manifest.status == "invalid_config"
    assert manifest.data == AgentBridgeManifest()
    assert manifest.errors
    assert "JSON" in manifest.errors[0] or "Expecting" in manifest.errors[0]


def test_redact_mapping_hides_secret_values():
    redacted = redact_mapping(
        {
            "GITHUB_TOKEN": "ghp_secret",
            "Authorization": "Bearer secret",
            "normal": "visible",
            "nested": {"password": "secret", "label": "ok"},
        }
    )

    assert redacted["GITHUB_TOKEN"] == "<redacted>"
    assert redacted["Authorization"] == "<redacted>"
    assert redacted["normal"] == "visible"
    assert redacted["nested"]["password"] == "<redacted>"
    assert redacted["nested"]["label"] == "ok"
