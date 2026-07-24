"""Provide command-line entry points for MCP and HTTP server, and remote-worker."""

import argparse
import sys

from .agent_bridge.cli import add_mcp_cli_parser
from .config.settings import configure_settings, load_settings
from .config.surface import cli_overrides_from_args, register_setting_cli_args
from .executors.http.app import run_http
from .executors.mcp.app import run_mcp
from .ops.jobs import run_job_runner_from_args
from .remote_worker.cli import add_worker_cli_parser
from .tui_runtime import run_tui
from .ui.security import UI_API_PREFIX
from .version import format_version_info


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser shared by server and remote-worker modes."""
    parser = argparse.ArgumentParser(
        prog="local-shell-mcp",
        description="Run a local-shell-mcp server or remote worker.",
    )
    parser.set_defaults(handler=_run_server_from_args)
    parser.add_argument(
        "--version",
        action="version",
        version=format_version_info(),
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help=(
            "Path to optional YAML config file. Overrides LOCAL_SHELL_MCP_CONFIG. "
            "This selects the config file and is not itself a Settings field."
        ),
    )
    register_setting_cli_args(parser)

    subparsers = parser.add_subparsers(dest="command")

    # version subcommand
    version = subparsers.add_parser(
        "version",
        help="Print local-shell-mcp version information",
    )
    version.set_defaults(handler=_print_version_from_args)

    # Agent Bridge credential administration
    add_mcp_cli_parser(subparsers)

    # worker enrollment and user-service management
    add_worker_cli_parser(subparsers)

    # native OpenTUI subcommand
    tui = subparsers.add_parser(
        "tui",
        help="Launch the optional native OpenTUI client",
    )
    tui.add_argument(
        "--api-base",
        default=None,
        metavar="URL",
        help=(
            "Loopback Human UI API base. Defaults to "
            "http://127.0.0.1:<port>/api/ui."
        ),
    )
    tui.set_defaults(handler=_run_tui_from_args)

    return parser


def _build_job_runner_parser() -> argparse.ArgumentParser:
    """Build the private parser used only by durable tracked-job attempts."""
    parser = argparse.ArgumentParser(prog="local-shell-mcp job-runner")
    parser.add_argument("--command-file", required=True)
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--shell", required=True)
    parser.add_argument("--max-log-bytes", type=int, required=True)
    return parser


def _print_version_from_args(args: argparse.Namespace) -> None:
    """Print detailed version information."""
    print(format_version_info())


def _run_tui_from_args(args: argparse.Namespace) -> None:
    """Load configuration and launch OpenTUI against the loopback HTTP service."""
    settings = load_settings(args.config, cli_overrides_from_args(args))
    configure_settings(settings)
    api_base = (
        args.api_base or f"http://127.0.0.1:{settings.port}{UI_API_PREFIX}"
    )
    raise SystemExit(run_tui(api_base, settings=settings))


def _run_server_from_args(args: argparse.Namespace) -> None:
    """Select MCP or HTTP server based on parsed CLI arguments."""
    settings = load_settings(args.config, cli_overrides_from_args(args))
    configure_settings(settings)
    match settings.mode:
        case "http":
            run_http()
        case "mcp" | "stdio":
            run_mcp()
        case "both":
            raise SystemExit(
                "mode=both is reserved; run separate mcp/http processes for now"
            )
        case _:
            raise SystemExit(f"Unsupported mode: {settings.mode}")


def main(argv: list[str] | None = None) -> None:
    """Parse CLI arguments and dispatch to public or private runtime modes."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "job-runner":
        args = _build_job_runner_parser().parse_args(arguments[1:])
        run_job_runner_from_args(args)
        return
    args = _build_parser().parse_args(arguments)
    args.handler(args)


if __name__ == "__main__":
    main()
