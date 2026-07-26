"""Dependency-leaf filesystem paths for the source-only worker runtime."""

import os
from pathlib import Path

_RUNTIME_METADATA_FILE_NAME = "runtime.json"


def worker_state_dir() -> Path:
    """Return the persistent state directory for one worker installation."""
    configured = os.getenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    xdg_state_home = os.getenv("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / "local-shell-mcp-worker"
    return Path.home() / ".local" / "state" / "local-shell-mcp-worker"


def worker_runtime_dir() -> Path:
    """Return the atomically replaceable worker runtime directory."""
    return worker_state_dir() / "runtime"


def runtime_metadata_path() -> Path:
    """Return the persisted worker-runtime metadata path."""
    return worker_state_dir() / _RUNTIME_METADATA_FILE_NAME


def worker_lock_path() -> Path:
    """Return the persistent file used to serialize worker processes."""
    return worker_state_dir() / "worker.lock"
