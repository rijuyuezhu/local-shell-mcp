"""Executable remote-worker entrypoint."""

from .cli import run_worker_cli

if __name__ == "__main__":
    run_worker_cli()
