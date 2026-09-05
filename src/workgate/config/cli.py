"""Shared argparse contracts for configuration-backed CLI commands."""

import argparse

from .settings import (
    Settings,
    configure_settings,
    initialize_runtime_directories,
    load_settings,
)
from .surface import cli_overrides_from_args, register_setting_cli_args


def register_config_and_setting_args(parser: argparse.ArgumentParser) -> None:
    """Register config-file selection and all Settings overrides."""
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help=(
            "Path to optional YAML config file. Overrides WORKGATE_CONFIG. "
            "This selects the config file and is not itself a Settings field."
        ),
    )
    register_setting_cli_args(parser)


def settings_from_args(
    args: argparse.Namespace,
    *,
    configure: bool = False,
) -> Settings:
    """Load CLI-selected settings and optionally install them process-wide."""
    settings = load_settings(args.config, cli_overrides_from_args(args))
    if configure:
        initialize_runtime_directories(settings)
        configure_settings(settings)
    return settings
