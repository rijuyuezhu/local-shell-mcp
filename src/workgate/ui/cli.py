"""Command-line registration for the optional native OpenTUI client."""

import argparse
from typing import Any

from ..config.cli import register_config_and_setting_args, settings_from_args
from .runtime import run_tui
from .security import UI_API_PREFIX


def register_tui_cli(subparsers: Any) -> argparse.ArgumentParser:
    """Register the native TUI command and its runtime settings."""
    parser = subparsers.add_parser(
        "tui",
        help="Launch the optional native OpenTUI client",
        description="Launch the optional native OpenTUI client.",
    )
    register_config_and_setting_args(parser)
    parser.add_argument(
        "--api-base",
        default=None,
        metavar="URL",
        help=(
            "Loopback Human UI API base. Defaults to "
            "http://127.0.0.1:<port>/api/ui."
        ),
    )
    parser.set_defaults(handler=run_tui_from_args)
    return parser


def run_tui_from_args(args: argparse.Namespace) -> None:
    """Load settings and launch OpenTUI against the loopback HTTP service."""
    settings = settings_from_args(args, configure=True)
    api_base = (
        args.api_base or f"http://127.0.0.1:{settings.port}{UI_API_PREFIX}"
    )
    raise SystemExit(run_tui(api_base, settings=settings))
