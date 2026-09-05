"""Private persisted identities for legacy and profile-scoped workers."""

import contextlib
import json
from typing import Any

from ..utils.private_files import atomic_write_private_text
from .state import worker_identity_path


def read_worker_identity(
    server: str | None = None,
    requested_name: str | None = None,
    profile_id: str | None = None,
) -> dict[str, Any] | None:
    """Read a stored identity, optionally matching its controller and name."""
    path = worker_identity_path(profile_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if server is not None and data.get("server") != server:
        return None
    stored_name = str(data.get("name") or "")
    if requested_name and stored_name != requested_name:
        return None
    if not stored_name or not str(data.get("access") or ""):
        return None
    return data


def load_worker_identity(profile_id: str | None = None) -> dict[str, Any]:
    """Load the complete stored identity required by ``worker run``."""
    identity = read_worker_identity(profile_id=profile_id)
    if identity is None:
        raise ValueError("no stored worker identity; run worker enroll first")
    required = ("server", "name", "access", "workdir")
    missing = [name for name in required if not str(identity.get(name) or "")]
    if missing:
        raise ValueError(
            f"stored worker identity is incomplete: missing {missing[0]}"
        )
    return identity


def write_worker_identity(
    data: dict[str, Any], profile_id: str | None = None
) -> None:
    """Persist a worker identity atomically with owner-only permissions."""
    atomic_write_private_text(
        worker_identity_path(profile_id),
        json.dumps(data, indent=2, sort_keys=True),
    )


def delete_worker_identity(profile_id: str | None = None) -> None:
    """Remove a stored identity after the controller rejects it."""
    with contextlib.suppress(FileNotFoundError):
        worker_identity_path(profile_id).unlink()
