"""Private argparse registration for durable tracked-job runner attempts."""

import argparse
from typing import Any

from .runtime import run_job_runner_from_args


def register_job_runner_cli(subparsers: Any) -> argparse.ArgumentParser:
    """Register the internal runner as a normal argparse subcommand."""
    parser = subparsers.add_parser(
        "job-runner",
        help="Run one durable job attempt (internal)",
        description="Run one durable tracked-job attempt. Internal interface.",
    )
    parser.add_argument("--command-file", required=True)
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--shell", required=True)
    parser.add_argument("--max-log-bytes", type=int, required=True)
    parser.set_defaults(handler=run_job_runner_from_args)
    return parser
