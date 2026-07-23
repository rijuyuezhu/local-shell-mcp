import argparse
import json
import textwrap

import pytest
from mcp.shared.auth import OAuthToken

import local_shell_mcp.agent_bridge.cli as agent_cli
import local_shell_mcp.main as cli
from local_shell_mcp import __version__
from local_shell_mcp.agent_bridge.auth_store import AgentAuthStore
from local_shell_mcp.config.surface import (
    SETTING_SPECS,
    cli_overrides_from_args,
)


class NoBreakHelpFormatter(argparse.HelpFormatter):
    """Formatter used by tests to keep long environment variable names intact."""

    def _split_lines(self, text, width):
        return textwrap.wrap(
            text,
            width,
            break_long_words=False,
            break_on_hyphens=False,
        )

    def _fill_text(self, text, width, indent):
        return "\n".join(
            textwrap.wrap(
                text,
                width,
                initial_indent=indent,
                subsequent_indent=indent,
                break_long_words=False,
                break_on_hyphens=False,
            )
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
            "--base-url",
            "https://example.com",
            "--oauth-admin-pin",
            "pin",
            "--allow-full-control",
            "true",
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
    assert args.base_url == "https://example.com"
    assert args.oauth_admin_pin == "pin"
    assert args.allow_full_control is True
    assert args.remote_enabled is False


def test_version_option_prints_package_version(capsys):
    parser = cli._build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out == f"local-shell-mcp {__version__}\n"


def test_version_subcommand_prints_package_version(capsys):
    args = cli._build_parser().parse_args(["version"])

    args.handler(args)

    assert capsys.readouterr().out.startswith(f"local-shell-mcp {__version__}")


def test_every_setting_has_cli_option():
    parser = cli._build_parser()
    parser.formatter_class = NoBreakHelpFormatter
    help_text = parser.format_help()

    assert "<object object at" not in help_text
    assert "--audit-log-path" not in help_text
    assert "--agent-config-dir" not in help_text
    for spec in SETTING_SPECS:
        assert spec.cli_flag in help_text
        assert spec.env_var in help_text
        if spec.is_nullable:
            assert spec.unset_cli_flag in help_text
        else:
            assert spec.unset_cli_flag not in help_text


def test_nullable_cli_values_can_be_explicitly_unset():
    args = cli._build_parser().parse_args(
        ["--unset-base-url", "--unset-oauth-admin-pin"]
    )

    assert args.base_url is None
    assert args.oauth_admin_pin is None
    assert cli_overrides_from_args(args) == {
        "base_url": None,
        "oauth_admin_pin": None,
    }


def test_nullable_cli_value_and_unset_flag_are_mutually_exclusive():
    parser = cli._build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--base-url",
                "https://example.com",
                "--unset-base-url",
            ]
        )


def test_bool_cli_values_parse_explicitly():
    parser = cli._build_parser()

    assert (
        parser.parse_args(["--allow-full-control", "true"]).allow_full_control
        is True
    )
    assert (
        parser.parse_args(["--allow-full-control", "false"]).allow_full_control
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


def test_tui_subcommand_parses_loopback_api_base():
    args = cli._build_parser().parse_args(
        ["--port", "9443", "tui", "--api-base", "https://localhost:9443/api/ui"]
    )

    assert args.handler is cli._run_tui_from_args
    assert args.port == 9443
    assert args.api_base == "https://localhost:9443/api/ui"


def test_tui_handler_uses_configured_port_and_settings(monkeypatch):
    calls = []

    def fake_run(api_base, *, settings):
        calls.append((api_base, settings.port, settings.ui_tui_command))
        return 0

    monkeypatch.setattr(cli, "run_tui", fake_run)
    args = cli._build_parser().parse_args(
        ["--port", "9555", "--ui-tui-command", "/opt/tui", "tui"]
    )

    with pytest.raises(SystemExit) as exc_info:
        args.handler(args)

    assert exc_info.value.code == 0
    assert calls == [("http://127.0.0.1:9555/api/ui", 9555, "/opt/tui")]


def test_main_dispatches_to_argparse_handler(monkeypatch):
    calls = []

    def run_from_args(args):
        calls.append((args.mode, args.remote_enabled))

    monkeypatch.setattr(cli, "_run_server_from_args", run_from_args)

    cli.main(["--mode", "stdio", "--remote-enabled", "true"])

    assert calls == [("stdio", True)]


def test_private_job_runner_is_hidden_and_dispatches_directly(monkeypatch):
    public_help = cli._build_parser().format_help()
    calls = []

    def run_job_runner(args):
        calls.append(
            (
                args.command_file,
                args.log_file,
                args.status_file,
                args.cwd,
                args.shell,
                args.max_log_bytes,
            )
        )

    monkeypatch.setattr(cli, "run_job_runner_from_args", run_job_runner)

    assert "job-runner" not in public_help
    cli.main(
        [
            "job-runner",
            "--command-file",
            "command.txt",
            "--log-file",
            "job.log",
            "--status-file",
            "status.json",
            "--cwd",
            "/tmp/work",
            "--shell",
            "/bin/sh",
            "--max-log-bytes",
            "1234",
        ]
    )

    assert calls == [
        (
            "command.txt",
            "job.log",
            "status.json",
            "/tmp/work",
            "/bin/sh",
            1234,
        )
    ]


def test_server_overrides_include_only_explicit_values():
    args = cli._build_parser().parse_args(
        ["--mode", "stdio", "--remote-enabled", "false"]
    )

    assert cli_overrides_from_args(args) == {
        "mode": "stdio",
        "remote_enabled": False,
    }


def _write_agent_manifest(state_dir, server):
    config_dir = state_dir / "agent_config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.json").write_text(
        json.dumps({"version": 1, "mcpServers": {"docs": server}}),
        encoding="utf-8",
    )


def test_mcp_credential_subcommands_parse_to_public_handler():
    parser = cli._build_parser()

    auth = parser.parse_args(["mcp", "auth", "docs", "--status"])
    no_open = parser.parse_args(["mcp", "auth", "docs", "--no-open"])
    secret_set = parser.parse_args(
        ["mcp", "secret", "set", "docs", "token", "--stdin"]
    )
    secret_list = parser.parse_args(["mcp", "secret", "list", "docs"])
    secret_delete = parser.parse_args(
        ["mcp", "secret", "delete", "docs", "token"]
    )

    assert auth.handler is agent_cli.run_mcp_cli_from_args
    assert auth.status is True
    assert no_open.no_open is True
    assert secret_set.stdin is True
    assert secret_list.server == "docs"
    assert secret_delete.name == "token"


def test_mcp_auth_actions_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        cli._build_parser().parse_args(
            ["mcp", "auth", "docs", "--status", "--no-open"]
        )


def test_mcp_secret_set_list_delete_never_print_values(
    monkeypatch, tmp_path, capsys
):
    state_dir = tmp_path / "state"
    _write_agent_manifest(
        state_dir,
        {
            "type": "http",
            "url": "https://example.test/mcp",
            "enabled": False,
            "headers": {"Authorization": {"secret": "token"}},
            "auth": {"mode": "secret"},
        },
    )
    parser = cli._build_parser()
    monkeypatch.setattr(
        agent_cli, "_read_secret_stdin", lambda: "private-value"
    )

    set_args = parser.parse_args(
        [
            "--state-dir",
            str(state_dir),
            "mcp",
            "secret",
            "set",
            "docs",
            "token",
            "--stdin",
        ]
    )
    set_args.handler(set_args)
    set_output = capsys.readouterr().out
    assert "private-value" not in set_output
    assert json.loads(set_output)["stored"] is True
    store = AgentAuthStore(state_dir / "agent_auth")
    assert store.get_secret("docs", "token") == "private-value"

    list_args = parser.parse_args(
        ["--state-dir", str(state_dir), "mcp", "secret", "list", "docs"]
    )
    list_args.handler(list_args)
    list_output = capsys.readouterr().out
    assert "private-value" not in list_output
    assert json.loads(list_output) == {"secrets": {"docs": ["token"]}}

    delete_args = parser.parse_args(
        [
            "--state-dir",
            str(state_dir),
            "mcp",
            "secret",
            "delete",
            "docs",
            "token",
        ]
    )
    delete_args.handler(delete_args)
    assert json.loads(capsys.readouterr().out)["deleted"] is True
    assert store.list_secrets("docs") == {}


def test_mcp_auth_status_reports_only_safe_metadata(tmp_path, capsys):
    state_dir = tmp_path / "state"
    _write_agent_manifest(
        state_dir,
        {
            "type": "http",
            "url": "https://example.test/mcp",
            "enabled": False,
            "auth": {"mode": "oauth", "scopes": ["tools.read"]},
        },
    )
    args = cli._build_parser().parse_args(
        ["--state-dir", str(state_dir), "mcp", "auth", "docs", "--status"]
    )

    args.handler(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "authorized": False,
        "client_registered": False,
        "expires_at": None,
        "mode": "oauth",
        "server": "docs",
        "status": "unauthorized",
    }


def test_mcp_auth_no_open_runs_interactive_authorization(
    monkeypatch, tmp_path, capsys
):
    state_dir = tmp_path / "state"
    _write_agent_manifest(
        state_dir,
        {
            "type": "http",
            "url": "https://example.test/mcp",
            "enabled": False,
            "auth": {"mode": "oauth"},
        },
    )
    calls = []

    async def fake_authorize(settings, server_name, server, *, no_open):
        calls.append((settings.state_dir, server_name, server.url, no_open))
        return {"server": server_name, "authorized": True}

    monkeypatch.setattr(agent_cli, "authorize_server", fake_authorize)
    args = cli._build_parser().parse_args(
        ["--state-dir", str(state_dir), "mcp", "auth", "docs", "--no-open"]
    )

    args.handler(args)

    assert calls == [
        (state_dir.resolve(), "docs", "https://example.test/mcp", True)
    ]
    assert json.loads(capsys.readouterr().out)["authorized"] is True


def test_mcp_logout_reports_revocation_and_clears_local_credentials(
    monkeypatch, tmp_path, capsys
):
    state_dir = tmp_path / "state"
    _write_agent_manifest(
        state_dir,
        {
            "type": "http",
            "url": "https://example.test/mcp",
            "enabled": False,
            "auth": {"mode": "oauth"},
        },
    )
    store = AgentAuthStore(state_dir / "agent_auth")
    store.set_tokens(
        "docs",
        OAuthToken.model_validate(
            {"access_token": "access", "token_type": "Bearer"}
        ),
    )

    async def fake_revoke(_store, server_name, server):
        assert server_name == "docs"
        assert server.url == "https://example.test/mcp"
        return agent_cli.RevocationResult(
            "unsupported", "no revocation endpoint advertised"
        )

    monkeypatch.setattr(agent_cli, "revoke_stored_oauth", fake_revoke)
    args = cli._build_parser().parse_args(
        ["--state-dir", str(state_dir), "mcp", "auth", "docs", "--logout"]
    )

    args.handler(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["remote_revocation"] == "unsupported"
    assert payload["local_credentials_cleared"] is True
    assert store.get_tokens("docs") is None


def test_secret_stdin_reader_validates_tty_size_encoding_and_newlines(
    monkeypatch,
):
    import io
    from types import SimpleNamespace

    def install(data: bytes, *, tty: bool = False):
        monkeypatch.setattr(
            agent_cli.sys,
            "stdin",
            SimpleNamespace(isatty=lambda: tty, buffer=io.BytesIO(data)),
        )

    install(b"ignored", tty=True)
    with pytest.raises(ValueError, match="interactive terminal"):
        agent_cli._read_secret_stdin()

    install(b"x" * 65_537)
    with pytest.raises(ValueError, match="exceeds"):
        agent_cli._read_secret_stdin()

    install(b"\xff")
    with pytest.raises(ValueError, match="UTF-8"):
        agent_cli._read_secret_stdin()

    install(b"value\r\n")
    assert agent_cli._read_secret_stdin() == "value"
    install(b"value\n")
    assert agent_cli._read_secret_stdin() == "value"
    install(b"")
    with pytest.raises(ValueError, match="must not be empty"):
        agent_cli._read_secret_stdin()


def test_mcp_cli_reports_manifest_and_server_errors(tmp_path, capsys):
    state_dir = tmp_path / "state"
    parser = cli._build_parser()
    missing_manifest = parser.parse_args(
        ["--state-dir", str(state_dir), "mcp", "auth", "docs", "--status"]
    )
    with pytest.raises(SystemExit, match="2"):
        missing_manifest.handler(missing_manifest)
    assert "manifest is unavailable" in capsys.readouterr().err

    _write_agent_manifest(
        state_dir,
        {
            "type": "http",
            "url": "https://example.test/mcp",
            "enabled": False,
        },
    )
    unknown = parser.parse_args(
        ["--state-dir", str(state_dir), "mcp", "auth", "unknown", "--status"]
    )
    with pytest.raises(SystemExit, match="2"):
        unknown.handler(unknown)
    assert "Unknown Agent Bridge MCP server" in capsys.readouterr().err

    non_oauth = parser.parse_args(
        ["--state-dir", str(state_dir), "mcp", "auth", "docs", "--status"]
    )
    with pytest.raises(SystemExit, match="2"):
        non_oauth.handler(non_oauth)
    assert "not configured for OAuth" in capsys.readouterr().err


def test_mcp_cli_failed_remote_revocation_exits_one(
    monkeypatch, tmp_path, capsys
):
    state_dir = tmp_path / "state"
    _write_agent_manifest(
        state_dir,
        {
            "type": "http",
            "url": "https://example.test/mcp",
            "enabled": False,
            "auth": {"mode": "oauth"},
        },
    )

    async def fake_revoke(*_args):
        return agent_cli.RevocationResult("failed", "remote unavailable")

    monkeypatch.setattr(agent_cli, "revoke_stored_oauth", fake_revoke)
    args = cli._build_parser().parse_args(
        ["--state-dir", str(state_dir), "mcp", "auth", "docs", "--logout"]
    )
    with pytest.raises(SystemExit, match="1"):
        args.handler(args)
    payload = json.loads(capsys.readouterr().out)
    assert payload["remote_revocation"] == "failed"
    assert payload["detail"] == "remote unavailable"


def test_mcp_cli_rejects_unknown_secret_dispatch(monkeypatch, tmp_path, capsys):
    from argparse import Namespace

    state_dir = tmp_path / "state"
    args = Namespace(
        config=None,
        state_dir=str(state_dir),
        mcp_command="secret",
        secret_command="unknown",
        server="docs",
        name="token",
    )
    monkeypatch.setattr(
        agent_cli,
        "_settings_from_args",
        lambda _args: agent_cli.load_settings(
            None, {"state_dir": str(state_dir)}
        ),
    )
    with pytest.raises(SystemExit, match="2"):
        agent_cli.run_mcp_cli_from_args(args)
    assert "unsupported secret command" in capsys.readouterr().err
