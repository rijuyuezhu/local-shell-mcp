"""Safe migration from the legacy single-worker state layout."""

import contextlib
import json
import secrets
import shutil
import time
from typing import Any

from ..utils.private_files import atomic_write_private_text, private_file_lock
from . import runtime
from .identity import (
    load_worker_identity,
    read_worker_identity,
    write_worker_identity,
)
from .profile_launcher import (
    ensure_profile_launcher,
    profile_reconnect_command,
)
from .profiles import read_worker_profile, update_worker_profile
from .state import (
    worker_legacy_migration_path,
    worker_migration_lock_path,
    worker_profile_dir,
    worker_profiles_dir,
)

LEGACY_MIGRATION_SCHEMA_VERSION = 1
_LEGACY_MIGRATION_SOURCE = "legacy-single-worker"
_MAX_PROFILE_SCAN = 1_024


def _migration_result(
    profile_id: str,
    profile: dict[str, Any],
) -> dict[str, Any]:
    identity = load_worker_identity(profile_id)
    if identity.get("migration_source") != _LEGACY_MIGRATION_SOURCE:
        raise ValueError("migrated worker identity has an invalid source")
    digest = str(profile.get("runtime_sha256") or "")
    installed = runtime.runtime_identity(digest)
    if installed.get("sha256") != digest:
        raise ValueError("migrated worker runtime is unavailable")
    return {
        "schema_version": LEGACY_MIGRATION_SCHEMA_VERSION,
        "profile_id": profile_id,
        "runtime_sha256": digest,
        "runtime_version": str(profile.get("runtime_version") or ""),
        "server": str(identity.get("server") or ""),
        "name": str(identity.get("name") or ""),
        "workdir": str(identity.get("workdir") or ""),
        "reconnect_command": profile_reconnect_command(profile_id),
    }


def _read_migration_marker() -> str | None:
    path = worker_legacy_migration_path()
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(
            "legacy worker migration marker is unreadable"
        ) from exc
    if not isinstance(decoded, dict):
        raise ValueError("legacy worker migration marker must be a JSON object")
    if decoded.get("schema_version") != LEGACY_MIGRATION_SCHEMA_VERSION:
        raise ValueError("unsupported legacy worker migration marker")
    profile_id = decoded.get("profile_id")
    if not isinstance(profile_id, str):
        raise ValueError("legacy worker migration marker has no profile id")
    worker_profile_dir(profile_id)
    return profile_id


def _write_migration_marker(profile_id: str) -> None:
    worker_profile_dir(profile_id)
    atomic_write_private_text(
        worker_legacy_migration_path(),
        json.dumps(
            {
                "schema_version": LEGACY_MIGRATION_SCHEMA_VERSION,
                "profile_id": profile_id,
                "migrated_at": time.time(),
            },
            indent=2,
            sort_keys=True,
        ),
    )


def _legacy_identity() -> dict[str, Any] | None:
    return read_worker_identity()


def _matching_orphan_profile(
    legacy_identity: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    profiles = worker_profiles_dir()
    if not profiles.is_dir():
        return None
    expected = {
        key: str(legacy_identity.get(key) or "")
        for key in ("server", "name", "access", "workdir")
    }
    for index, path in enumerate(sorted(profiles.iterdir())):
        if index >= _MAX_PROFILE_SCAN:
            break
        if not path.is_dir():
            continue
        profile_id = path.name
        try:
            worker_profile_dir(profile_id)
            identity = read_worker_identity(profile_id=profile_id)
            profile = read_worker_profile(profile_id)
        except ValueError:
            continue
        if identity is None:
            continue
        if identity.get("migration_source") != _LEGACY_MIGRATION_SOURCE:
            continue
        actual = {
            key: str(identity.get(key) or "")
            for key in ("server", "name", "access", "workdir")
        }
        if actual == expected:
            return profile_id, profile
    return None


def _install_current_runtime(server: str) -> dict[str, str]:
    installed = runtime.update_installed_runtime(server)
    digest = str(installed.get("sha256") or "")
    version = str(installed.get("version") or "")
    identity = runtime.runtime_identity(digest)
    if identity.get("sha256") != digest or not version:
        raise RuntimeError("installed worker runtime is incomplete")
    return {"sha256": digest, "version": version}


def _repair_profile_runtime(
    profile_id: str,
    profile: dict[str, Any],
) -> dict[str, Any]:
    identity = load_worker_identity(profile_id)
    if identity.get("migration_source") != _LEGACY_MIGRATION_SOURCE:
        raise ValueError("migrated worker identity has an invalid source")
    digest = str(profile.get("runtime_sha256") or "")
    if runtime.runtime_identity(digest).get("sha256") == digest:
        ensure_profile_launcher()
        return _migration_result(profile_id, profile)
    installed = _install_current_runtime(str(identity["server"]))
    repaired = update_worker_profile(
        profile_id,
        runtime_sha256=installed["sha256"],
        runtime_version=installed["version"],
        server=str(identity["server"]),
        name=str(identity["name"]),
        workdir=str(identity["workdir"]),
    )
    ensure_profile_launcher()
    return _migration_result(profile_id, repaired)


def migrated_legacy_profile() -> dict[str, Any] | None:
    """Return a complete migrated profile without creating new state."""
    profile_id = _read_migration_marker()
    if profile_id is None:
        return None
    profile = read_worker_profile(profile_id)
    return _migration_result(profile_id, profile)


def migrate_legacy_worker_state() -> dict[str, Any] | None:
    """Create one profile from legacy state while retaining the legacy files."""
    with private_file_lock(worker_migration_lock_path()):
        profile_id = _read_migration_marker()
        if profile_id is not None:
            return _repair_profile_runtime(
                profile_id, read_worker_profile(profile_id)
            )

        legacy_identity = _legacy_identity()
        if legacy_identity is None:
            return None

        orphan = _matching_orphan_profile(legacy_identity)
        if orphan is not None:
            profile_id, profile = orphan
            result = _repair_profile_runtime(profile_id, profile)
            _write_migration_marker(profile_id)
            return result

        server = str(legacy_identity.get("server") or "")
        if not server:
            raise ValueError("legacy worker identity has no server")
        installed = _install_current_runtime(server)
        while True:
            profile_id = f"p_{secrets.token_hex(8)}"
            profile_dir = worker_profile_dir(profile_id)
            if not profile_dir.exists():
                break

        stored = {
            **legacy_identity,
            "profile_id": profile_id,
            "migration_source": _LEGACY_MIGRATION_SOURCE,
        }
        try:
            write_worker_identity(stored, profile_id)
            profile = update_worker_profile(
                profile_id,
                runtime_sha256=installed["sha256"],
                runtime_version=installed["version"],
                server=server,
                name=str(legacy_identity.get("name") or ""),
                workdir=str(legacy_identity.get("workdir") or ""),
            )
            ensure_profile_launcher()
            result = _migration_result(profile_id, profile)
            _write_migration_marker(profile_id)
            return result
        except BaseException:
            with contextlib.suppress(OSError):
                shutil.rmtree(profile_dir)
            raise
