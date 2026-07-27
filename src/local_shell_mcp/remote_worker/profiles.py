"""Private non-secret metadata for independently runnable worker profiles."""

import contextlib
import json
import os
import uuid
from typing import Any

from .state import worker_profile_metadata_path, worker_runtime_dir_for_digest

PROFILE_SCHEMA_VERSION = 1
_PROFILE_TEXT_LIMITS = {
    "runtime_version": 128,
    "server": 4_096,
    "name": 512,
    "workdir": 4_096,
}


def _bounded_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"worker profile {key} must be a string")
    if len(value.encode("utf-8")) > _PROFILE_TEXT_LIMITS[key]:
        raise ValueError(f"worker profile {key} is too large")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"worker profile {key} contains control characters")
    return value


def _validated_profile(profile_id: str, data: dict[str, Any]) -> dict[str, Any]:
    if data.get("schema_version") != PROFILE_SCHEMA_VERSION:
        raise ValueError("unsupported remote worker profile schema")
    if data.get("profile_id") != profile_id:
        raise ValueError("remote worker profile id does not match its path")
    digest = data.get("runtime_sha256")
    if not isinstance(digest, str):
        raise ValueError("worker profile runtime_sha256 must be a string")
    worker_runtime_dir_for_digest(digest)
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profile_id": profile_id,
        "runtime_sha256": digest,
        **{key: _bounded_text(data, key) for key in _PROFILE_TEXT_LIMITS},
    }


def read_worker_profile(profile_id: str) -> dict[str, Any]:
    """Read and validate one profile's non-secret runtime metadata."""
    path = worker_profile_metadata_path(profile_id)
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"worker profile is unreadable: {profile_id}") from exc
    if not isinstance(decoded, dict):
        raise ValueError("worker profile must be a JSON object")
    return _validated_profile(profile_id, decoded)


def write_worker_profile(
    profile_id: str, data: dict[str, Any]
) -> dict[str, Any]:
    """Validate and atomically persist one profile without credentials."""
    normalized = _validated_profile(profile_id, data)
    path = worker_profile_metadata_path(profile_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(normalized, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        with contextlib.suppress(OSError):
            temporary.chmod(0o600)
        os.replace(temporary, path)
        with contextlib.suppress(OSError):
            path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)
    return normalized


def update_worker_profile(
    profile_id: str,
    *,
    runtime_sha256: str,
    runtime_version: str = "",
    server: str = "",
    name: str = "",
    workdir: str = "",
) -> dict[str, Any]:
    """Create or replace one complete profile metadata record."""
    return write_worker_profile(
        profile_id,
        {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "profile_id": profile_id,
            "runtime_sha256": runtime_sha256,
            "runtime_version": runtime_version,
            "server": server,
            "name": name,
            "workdir": workdir,
        },
    )
