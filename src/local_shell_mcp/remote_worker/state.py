"""Dependency-leaf filesystem paths for the source-only worker runtime."""

import os
import re
from pathlib import Path

_RUNTIME_METADATA_FILE_NAME = "runtime.json"
_PROFILE_METADATA_FILE_NAME = "profile.json"
WORKER_PROFILE_ID_ENV = "LOCAL_SHELL_MCP_WORKER_PROFILE_ID"
_PROFILE_ID_RE = re.compile(r"p_[A-Za-z0-9_-]{8,64}")
_RUNTIME_DIGEST_RE = re.compile(r"[0-9a-f]{64}")


def worker_state_dir() -> Path:
    """Return the persistent state directory for one worker installation."""
    configured = os.getenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    xdg_state_home = os.getenv("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / "local-shell-mcp-worker"
    return Path.home() / ".local" / "state" / "local-shell-mcp-worker"


def worker_profiles_dir() -> Path:
    """Return the root containing independent worker profiles."""
    return worker_state_dir() / "profiles"


def worker_profile_dir(profile_id: str) -> Path:
    """Return one validated worker-profile directory."""
    if not _PROFILE_ID_RE.fullmatch(profile_id):
        raise ValueError("invalid remote worker profile id")
    return worker_profiles_dir() / profile_id


def active_worker_profile_id() -> str | None:
    """Return the validated profile selected for the current process."""
    profile_id = os.getenv(WORKER_PROFILE_ID_ENV)
    if not profile_id:
        return None
    worker_profile_dir(profile_id)
    return profile_id


def activate_worker_profile(profile_id: str | None) -> str | None:
    """Select one profile for process re-exec and worker path resolution."""
    if profile_id is None:
        return active_worker_profile_id()
    worker_profile_dir(profile_id)
    os.environ[WORKER_PROFILE_ID_ENV] = profile_id
    return profile_id


def worker_profile_metadata_path(profile_id: str) -> Path:
    """Return the non-secret metadata file for one worker profile."""
    return worker_profile_dir(profile_id) / _PROFILE_METADATA_FILE_NAME


def worker_profile_identity_path(profile_id: str) -> Path:
    """Return the private controller identity file for one worker profile."""
    return worker_profile_dir(profile_id) / "identity.json"


def worker_identity_path(profile_id: str | None = None) -> Path:
    """Return one profile identity path or the legacy identity path."""
    selected = (
        profile_id if profile_id is not None else active_worker_profile_id()
    )
    if selected is not None:
        return worker_profile_identity_path(selected)
    return worker_state_dir() / "identity.json"


def worker_profile_lock_path(profile_id: str) -> Path:
    """Return the process lock for one independently runnable profile."""
    return worker_profile_dir(profile_id) / "worker.lock"


def worker_runtimes_dir() -> Path:
    """Return the root containing immutable content-addressed runtimes."""
    return worker_state_dir() / "runtimes"


def worker_runtime_dir_for_digest(digest: str) -> Path:
    """Return one validated SHA-256-addressed runtime directory."""
    if not _RUNTIME_DIGEST_RE.fullmatch(digest):
        raise ValueError("invalid remote worker runtime digest")
    return worker_runtimes_dir() / digest


def runtime_metadata_path_for_digest(digest: str) -> Path:
    """Return the metadata path stored beside one immutable runtime."""
    return worker_runtime_dir_for_digest(digest) / _RUNTIME_METADATA_FILE_NAME


def worker_launcher_path() -> Path:
    """Return the stable user-facing worker launcher path."""
    return worker_state_dir() / "run"


def worker_install_lock_path() -> Path:
    """Return the lock serializing shared runtime installation."""
    return worker_state_dir() / "install.lock"


def worker_runtime_dir() -> Path:
    """Return the legacy atomically replaceable worker runtime directory."""
    return worker_state_dir() / "runtime"


def runtime_metadata_path() -> Path:
    """Return the legacy persisted worker-runtime metadata path."""
    return worker_state_dir() / _RUNTIME_METADATA_FILE_NAME


def worker_lock_path(profile_id: str | None = None) -> Path:
    """Return the process lock for one profile or the legacy worker."""
    if profile_id is not None:
        return worker_profile_lock_path(profile_id)
    return worker_state_dir() / "worker.lock"
