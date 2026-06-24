"""Provide command-line entry points for MCP and HTTP server, and remote-worker."""

import argparse

from .config.settings import configure_settings, load_settings
from .config.surface import cli_overrides_from_args, register_setting_cli_args
from .remote.worker import add_worker_cli_args, run_worker_from_args
from .server.http.app import run_http
from .server.mcp.app import run_mcp
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

    # worker subcommand
    subparsers = parser.add_subparsers(dest="command")
    version = subparsers.add_parser(
        "version",
        help="Print local-shell-mcp version information",
    )
    version.set_defaults(handler=_print_version_from_args)

    worker = subparsers.add_parser(
        "worker",
        help="Connect this machine to a local-shell-mcp control server",
    )
    add_worker_cli_args(worker)
    worker.set_defaults(handler=run_worker_from_args)
    return parser


def _print_version_from_args(args: argparse.Namespace) -> None:
    """Print detailed version information."""
    print(format_version_info())


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
    """Parse CLI arguments and dispatch to server or worker mode."""
    args = _build_parser().parse_args(argv)
    args.handler(args)


if __name__ == "__main__":
    main()
