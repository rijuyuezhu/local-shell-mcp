"""Persistent storage for dynamically registered OAuth clients."""

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ...config.settings import get_settings
from .models import _CLIENTS, OAuthClient

CLIENT_STORE_FILENAME = "oauth-clients.json"
CLIENT_STORE_VERSION = 1


def client_store_path() -> Path:
    """Return the configured persistent OAuth client registry path."""
    return get_settings().state_dir / CLIENT_STORE_FILENAME


def _decode_client(raw: object) -> OAuthClient:
    """Validate and decode one client registry record."""
    if not isinstance(raw, dict):
        raise ValueError("OAuth client record must be an object")
    data: dict[str, Any] = raw
    client_id = data.get("client_id")
    redirect_uris = data.get("redirect_uris")
    client_name = data.get("client_name")
    created_at = data.get("created_at")
    if not isinstance(client_id, str) or not client_id:
        raise ValueError("OAuth client record has an invalid client_id")
    if not isinstance(redirect_uris, list) or not all(
        isinstance(uri, str) and uri for uri in redirect_uris
    ):
        raise ValueError("OAuth client record has invalid redirect_uris")
    if client_name is not None and not isinstance(client_name, str):
        raise ValueError("OAuth client record has an invalid client_name")
    if not isinstance(created_at, int):
        raise ValueError("OAuth client record has an invalid created_at")
    return OAuthClient(
        client_id=client_id,
        redirect_uris=redirect_uris,
        client_name=client_name,
        created_at=created_at,
    )


def load_persisted_clients() -> int:
    """Merge persisted dynamic clients into the active in-memory registry."""
    path = client_store_path()
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to read OAuth client registry: {path}") from exc
    if not isinstance(payload, dict) or payload.get("version") != CLIENT_STORE_VERSION:
        raise RuntimeError(f"Unsupported OAuth client registry format: {path}")
    records = payload.get("clients")
    if not isinstance(records, list):
        raise RuntimeError(f"Invalid OAuth client registry contents: {path}")

    loaded = 0
    for raw in records:
        try:
            client = _decode_client(raw)
        except ValueError as exc:
            raise RuntimeError(f"Invalid OAuth client registry contents: {path}") from exc
        current = _CLIENTS.get(client.client_id)
        if current is None or current.created_at <= client.created_at:
            _CLIENTS[client.client_id] = client
            loaded += 1
    return loaded


def persist_clients() -> None:
    """Atomically write the active dynamic client registry to disk."""
    path = client_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CLIENT_STORE_VERSION,
        "clients": [asdict(_CLIENTS[key]) for key in sorted(_CLIENTS)],
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
