"""Dependency-leaf filesystem paths for the trimmed worker runtime."""

import os
import re
import sys
from pathlib import Path

_APP_NAME = "workgate"


def _absolute_env_path(value: str | None) -> Path | None:
    """Accept an app-dir environment value only when it is already absolute."""
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        return None
    return path


def _default_worker_roots() -> tuple[Path, Path]:
    """Resolve bootstrap-compatible worker state/data roots with stdlib only."""
    home = Path.home().expanduser()
    if sys.platform == "darwin":
        support = home / "Library" / "Application Support" / _APP_NAME
        return support / "state" / "worker", support / "data" / "worker"
    if sys.platform.startswith("win"):
        local = _absolute_env_path(os.getenv("LOCALAPPDATA")) or (
            home / "AppData" / "Local"
        )
        return (
            local / _APP_NAME / "state" / "worker",
            local / _APP_NAME / "data" / "worker",
        )
    state_base = _absolute_env_path(os.getenv("XDG_STATE_HOME")) or (
        home / ".local" / "state"
    )
    data_base = _absolute_env_path(os.getenv("XDG_DATA_HOME")) or (
        home / ".local" / "share"
    )
    return state_base / _APP_NAME / "worker", data_base / _APP_NAME / "worker"


_RUNTIME_METADATA_FILE_NAME = "runtime.json"
_PROFILE_METADATA_FILE_NAME = "profile.json"
WORKER_PROFILE_ID_ENV = "WORKGATE_WORKER_PROFILE_ID"
WORKER_RUNTIME_DIGEST_ENV = "WORKGATE_WORKER_RUNTIME_SHA256"
WORKER_DATA_DIR_ENV = "WORKGATE_WORKER_DATA_DIR"
_PROFILE_ID_RE = re.compile(r"p_[A-Za-z0-9_-]{8,64}")
_RUNTIME_DIGEST_RE = re.compile(r"[0-9a-f]{64}")


def worker_state_dir() -> Path:
    """Return the absolute persistent state directory for one installation."""
    configured = os.getenv("WORKGATE_WORKER_STATE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    state_dir, _ = _default_worker_roots()
    return state_dir.resolve()


def worker_data_dir() -> Path:
    """Return the persistent installation-data directory for this worker."""
    configured = os.getenv(WORKER_DATA_DIR_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    legacy_state = os.getenv("WORKGATE_WORKER_STATE_DIR")
    if legacy_state:
        return Path(legacy_state).expanduser().resolve()
    _, data_dir = _default_worker_roots()
    return data_dir.resolve()


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
    """Return one profile identity path or the default identity path."""
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
    return worker_data_dir() / "runtimes"


def worker_runtime_dir_for_digest(digest: str) -> Path:
    """Return one validated SHA-256-addressed runtime directory."""
    if not _RUNTIME_DIGEST_RE.fullmatch(digest):
        raise ValueError("invalid remote worker runtime digest")
    return worker_runtimes_dir() / digest


def runtime_metadata_path_for_digest(digest: str) -> Path:
    """Return the metadata path stored beside one immutable runtime."""
    return worker_runtime_dir_for_digest(digest) / _RUNTIME_METADATA_FILE_NAME


def active_worker_runtime_digest() -> str | None:
    """Return the validated runtime digest selected for this process."""
    digest = os.getenv(WORKER_RUNTIME_DIGEST_ENV)
    if not digest:
        return None
    worker_runtime_dir_for_digest(digest)
    return digest


def activate_worker_runtime(digest: str | None) -> str | None:
    """Select one content-addressed runtime for process re-exec."""
    if digest is None:
        return active_worker_runtime_digest()
    worker_runtime_dir_for_digest(digest)
    os.environ[WORKER_RUNTIME_DIGEST_ENV] = digest
    return digest


def worker_launcher_path() -> Path:
    """Return the stable user-facing worker launcher path."""
    name = "run.cmd" if os.name == "nt" else "run"
    return worker_data_dir() / name


def worker_launcher_runner_path() -> Path:
    """Return the standalone Python runner used by the stable launcher."""
    return worker_data_dir() / "run.py"


def worker_python_path() -> Path:
    """Return the stored Python executable used by the stable launcher."""
    return worker_data_dir() / "python"


def worker_uv_path() -> Path:
    """Return the persisted uv executable used for runtime installation/upgrades."""
    name = "uv.exe" if os.name == "nt" else "uv"
    return worker_data_dir() / name


def runtime_python_path(runtime: Path) -> Path:
    """Return the Python executable in one uv-managed worker runtime."""
    if os.name == "nt":
        return runtime / ".venv" / "Scripts" / "python.exe"
    return runtime / ".venv" / "bin" / "python"


def worker_install_lock_path() -> Path:
    """Return the lock serializing shared runtime installation."""
    return worker_data_dir() / "install.lock"


def worker_runtime_dir(digest: str | None = None) -> Path:
    """Return the selected content-addressed or default runtime directory."""
    selected = digest if digest is not None else active_worker_runtime_digest()
    if selected is not None:
        return worker_runtime_dir_for_digest(selected)
    return worker_data_dir() / "runtime"


def runtime_metadata_path(digest: str | None = None) -> Path:
    """Return metadata for the selected content-addressed or default runtime."""
    selected = digest if digest is not None else active_worker_runtime_digest()
    if selected is not None:
        return runtime_metadata_path_for_digest(selected)
    return worker_data_dir() / _RUNTIME_METADATA_FILE_NAME


def worker_lock_path(profile_id: str | None = None) -> Path:
    """Return the process lock for one profile or the default worker."""
    if profile_id is not None:
        return worker_profile_lock_path(profile_id)
    return worker_state_dir() / "worker.lock"
