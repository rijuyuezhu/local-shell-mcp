"""Command-line registration for the selectable server executors."""

import argparse
from typing import Any

from ..config.cli import register_config_and_setting_args, settings_from_args
from .http.app import run_http
from .mcp.app import run_mcp
from .runtime_services import configure_runtime_services
from .search_composition import build_controller_tool_catalog


def register_server_cli(subparsers: Any) -> argparse.ArgumentParser:
    """Register the explicit server command and its Settings overrides."""
    parser = subparsers.add_parser(
        "server",
        help="Run the configured MCP or REST server",
        description="Run the configured MCP or REST server.",
    )
    register_config_and_setting_args(parser)
    parser.set_defaults(handler=run_server_from_args)
    return parser


def run_server_from_args(args: argparse.Namespace) -> None:
    """Load settings and launch the selected server executor."""
    settings = settings_from_args(args, configure=True)
    services = configure_runtime_services(settings)
    tool_catalog = build_controller_tool_catalog(
        settings, services.tool_session_store
    )
    match settings.mode:
        case "http":
            run_http(tool_catalog=tool_catalog)
        case "mcp" | "stdio":
            run_mcp(tool_catalog=tool_catalog)
        case "both":
            raise SystemExit(
                "mode=both is reserved; run separate mcp/http processes for now"
            )
        case _:
            raise SystemExit(f"Unsupported mode: {settings.mode}")
