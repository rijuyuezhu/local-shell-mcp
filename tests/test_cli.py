import pytest

import local_shell_mcp.main as cli
from local_shell_mcp import __version__
from local_shell_mcp.config.surface import (
    SETTING_SPECS,
    cli_overrides_from_args,
    is_nullable_setting,
)


def test_server_options_parse_to_default_handler():
    args = cli._build_parser().parse_args(
        [
            "--config",
            "config.yaml",
            "--mode",
            "stdio",
            "--host",
            "127.0.0.1",
            "--port",
            "9999",
            "--workspace-root",
            "/tmp/work",
            "--auth-mode",
            "none",
            "--public-base-url",
            "https://example.com",
            "--oauth-admin-pin",
            "pin",
            "--allow-full-container",
            "true",
            "--agent-config-dir",
            "/tmp/agent-config",
            "--remote-enabled",
            "false",
        ]
    )

    assert args.handler is cli._run_server_from_args
    assert args.config == "config.yaml"
    assert args.mode == "stdio"
    assert args.host == "127.0.0.1"
    assert args.port == 9999
    assert args.workspace_root == "/tmp/work"
    assert args.auth_mode == "none"
    assert args.public_base_url == "https://example.com"
    assert args.oauth_admin_pin == "pin"
    assert args.allow_full_container is True
    assert args.agent_config_dir == "/tmp/agent-config"
    assert args.remote_enabled is False


def test_version_option_prints_package_version(capsys):
    parser = cli._build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out == f"local-shell-mcp {__version__}\n"


def test_every_setting_has_cli_option():
    help_text = cli._build_parser().format_help()

    assert "<object object at" not in help_text
    for spec in SETTING_SPECS:
        assert spec.cli_flag in help_text
        assert spec.env_var in help_text
        if is_nullable_setting(spec.name):
            assert spec.unset_cli_flag in help_text
        else:
            assert spec.unset_cli_flag not in help_text


def test_nullable_cli_values_can_be_explicitly_unset():
    args = cli._build_parser().parse_args(
        ["--unset-public-base-url", "--unset-oauth-admin-pin"]
    )

    assert args.public_base_url is None
    assert args.oauth_admin_pin is None
    assert cli_overrides_from_args(args) == {
        "public_base_url": None,
        "oauth_admin_pin": None,
    }


def test_nullable_cli_value_and_unset_flag_are_mutually_exclusive():
    parser = cli._build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--public-base-url",
                "https://example.com",
                "--unset-public-base-url",
            ]
        )


def test_bool_cli_values_parse_explicitly():
    parser = cli._build_parser()

    assert (
        parser.parse_args(
            ["--allow-full-container", "true"]
        ).allow_full_container
        is True
    )
    assert (
        parser.parse_args(
            ["--allow-full-container", "false"]
        ).allow_full_container
        is False
    )
    assert (
        parser.parse_args(["--remote-enabled", "false"]).remote_enabled is False
    )
    assert (
        parser.parse_args(["--remote-enabled", "true"]).remote_enabled is True
    )


def test_worker_subcommand_parse_to_worker_handler():
    args = cli._build_parser().parse_args(
        [
            "worker",
            "--server",
            "https://example.com",
            "--invite",
            "lsmcp_inv_xxxxx",
            "--name",
            "npu-4card",
            "--workdir",
            "/home/user/project",
            "--persist",
        ]
    )

    assert args.handler is cli.run_worker_from_args
    assert args.server == "https://example.com"
    assert args.invite == "lsmcp_inv_xxxxx"
    assert args.name == "npu-4card"
    assert args.workdir == "/home/user/project"
    assert args.persist is True


def test_main_dispatches_to_argparse_handler(monkeypatch):
    calls = []

    def run_from_args(args):
        calls.append((args.mode, args.remote_enabled))

    monkeypatch.setattr(cli, "_run_server_from_args", run_from_args)

    cli.main(["--mode", "stdio", "--remote-enabled", "true"])

    assert calls == [("stdio", True)]


def test_server_overrides_include_only_explicit_values():
    args = cli._build_parser().parse_args(
        ["--mode", "stdio", "--remote-enabled", "false"]
    )

    assert cli_overrides_from_args(args) == {
        "mode": "stdio",
        "remote_enabled": False,
    }
