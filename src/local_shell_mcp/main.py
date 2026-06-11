"""Provide command-line entry points for stdio MCP, HTTP server, and remote-worker modes."""

from __future__ import annotations

import argparse

import uvicorn

from .config.registry import cli_overrides_from_args, register_setting_cli_args
from .config.settings import (
    configure_settings,
    get_settings,
    load_settings,
    validate_public_oauth_configuration,
)
from .http_app import build_http_app
from .mcp_app import run_mcp
from .remote import add_worker_cli_args, run_worker_from_args


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser shared by server and remote-worker modes."""
    parser = argparse.ArgumentParser(
        prog="local-shell-mcp",
        description="Run a local-shell-mcp server or remote worker.",
    )
    parser.set_defaults(handler=_run_server_from_args)
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
    worker = subparsers.add_parser(
        "worker",
        help="Connect this machine to a local-shell-mcp control server",
    )
    add_worker_cli_args(worker)
    worker.set_defaults(handler=run_worker_from_args)
    return parser


def _run_server_from_args(args: argparse.Namespace) -> None:
    """Select stdio MCP or HTTP server startup based on parsed CLI arguments."""
    settings = load_settings(args.config, cli_overrides_from_args(args))
    configure_settings(settings)
    if settings.mode == "http":
        run_http()
    elif settings.mode in {"mcp", "stdio"}:
        run_mcp()
    elif settings.mode == "both":
        raise SystemExit(
            "mode=both is reserved; run separate mcp/http processes for now"
        )
    else:
        raise SystemExit(f"Unsupported mode: {settings.mode}")


def run_http() -> None:
    """Run the HTTP server with FastAPI routes, MCP transport, OAuth metadata, and remote-worker endpoints."""
    settings = get_settings()
    validate_public_oauth_configuration(settings)
    app = build_http_app()
    uvicorn.run(app, host=settings.host, port=settings.port)


def main(argv: list[str] | None = None) -> None:
    """Parse CLI arguments and dispatch to server or worker mode."""
    args = _build_parser().parse_args(argv)
    args.handler(args)


if __name__ == "__main__":
    main()
