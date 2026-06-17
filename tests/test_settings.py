from local_shell_mcp.config.settings import load_settings


def test_settings_precedence_config_env_cli(monkeypatch, tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        """
host: 0.0.0.0
port: 1111
mode: http
workspace_root: config-workspace
auth_mode: oauth
""".strip()
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_PORT", "2222")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")

    settings = load_settings(
        config,
        {"mode": "stdio", "workspace_root": str(tmp_path / "cli-workspace")},
        create_dirs=False,
    )

    assert settings.host == "0.0.0.0"
    assert settings.port == 2222
    assert settings.mode == "stdio"
    assert settings.workspace_root == (tmp_path / "cli-workspace").resolve()
    assert settings.auth_mode == "none"


def test_settings_rejects_non_mapping_config(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("- not\n- a\n- mapping\n")

    try:
        load_settings(config, create_dirs=False)
    except ValueError as exc:
        assert "Config file must contain a mapping" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_config_file_uses_flat_keys_only(monkeypatch, tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        """
host: 127.0.0.1
auth:
  mode: none
""".strip()
    )
    monkeypatch.delenv("LOCAL_SHELL_MCP_AUTH_MODE", raising=False)

    settings = load_settings(config, create_dirs=False)

    assert settings.host == "127.0.0.1"
    assert settings.auth_mode == "oauth"


def test_none_overrides_clear_config_and_env_values(monkeypatch, tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("base_url: https://example.com\n")
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN", "test-pin")

    settings = load_settings(
        config,
        {"base_url": None, "oauth_admin_pin": None},
        create_dirs=False,
    )

    assert settings.base_url is None
    assert settings.oauth_admin_pin is None


def test_resolved_base_url_prefers_configured_base_url():
    settings = load_settings(
        overrides={"base_url": "https://example.com/"}, create_dirs=False
    )

    assert settings.resolved_base_url == "https://example.com"


def test_resolved_base_url_falls_back_to_host_and_port():
    settings = load_settings(
        overrides={"base_url": None, "host": "127.0.0.1", "port": 9999},
        create_dirs=False,
    )

    assert settings.resolved_base_url == "http://127.0.0.1:9999"


def test_resolved_base_url_normalizes_wildcard_host():
    settings = load_settings(
        overrides={"base_url": None, "host": "0.0.0.0", "port": 9999},
        create_dirs=False,
    )

    assert settings.resolved_base_url == "http://127.0.0.1:9999"


def test_resolved_base_url_brackets_ipv6_host():
    settings = load_settings(
        overrides={"base_url": None, "host": "::1", "port": 9999},
        create_dirs=False,
    )

    assert settings.resolved_base_url == "http://[::1]:9999"
