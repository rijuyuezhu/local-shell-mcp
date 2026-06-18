"""Tokenized file download link state and policy operations."""

import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from ..audit import audit
from ..config.settings import get_settings
from ..schemas.result_models.downloads import (
    CreateFileLinkOutput,
    FileLinkSummary,
    ListFileLinksOutput,
    RevokeFileLinkOutput,
)
from .path_ops import relative_display, resolve_path

DOWNLOAD_PREFIX = "/download"
DOWNLOAD_STORE_VERSION = 1
STORE_LOCK = threading.RLock()


def now_s() -> float:
    """Return the current Unix timestamp."""
    return time.time()


def download_store_path() -> Path:
    """Return the persistent download-link store path."""
    settings = get_settings()
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    return settings.state_dir / "downloads.json"


def empty_download_store() -> dict[str, Any]:
    """Return a new empty download-link store."""
    return {"version": DOWNLOAD_STORE_VERSION, "links": {}}


def read_download_store_locked() -> dict[str, Any]:
    """Read the download-link store while STORE_LOCK is held."""
    path = download_store_path()
    if not path.exists():
        return empty_download_store()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError, OSError:
        audit("download_store_unreadable", path=str(path))
        return empty_download_store()
    if not isinstance(data, dict) or not isinstance(data.get("links"), dict):
        return empty_download_store()
    data.setdefault("version", DOWNLOAD_STORE_VERSION)
    return data


def write_download_store_locked(store: dict[str, Any]) -> None:
    """Write the download-link store atomically while STORE_LOCK is held."""
    path = download_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp-{os.getpid()}-{secrets.token_hex(4)}")
    tmp.write_text(
        json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def coerce_download_ttl(ttl_s: int | None) -> int:
    """Clamp requested download-link lifetime to configured limits."""
    settings = get_settings()
    requested = (
        settings.file_download_default_ttl_s if ttl_s is None else int(ttl_s)
    )
    if requested <= 0:
        raise ValueError("ttl_s must be positive")
    return min(requested, settings.file_download_max_ttl_s)


def coerce_max_downloads(max_downloads: int | None) -> int:
    """Return a validated max-download count; 0 means unlimited."""
    settings = get_settings()
    requested = (
        settings.file_download_default_max_downloads
        if max_downloads is None
        else int(max_downloads)
    )
    if requested < 0:
        raise ValueError("max_downloads must be >= 0; use 0 for unlimited")
    return requested


def safe_download_filename(filename: str | None, source: Path) -> str:
    """Return a path-free, non-empty download filename."""
    candidate = Path(filename).name if filename else source.name
    candidate = candidate.strip().replace("\x00", "")
    return candidate or "download"


def download_link_summary(token: str, link: dict[str, Any]) -> FileLinkSummary:
    """Return the public summary for a stored download link."""
    return FileLinkSummary(
        token=token,
        url=f"{get_settings().resolved_base_url}{DOWNLOAD_PREFIX}/{token}",
        path=link.get("display_path"),
        filename=link.get("filename"),
        bytes=link.get("bytes"),
        created_at=link.get("created_at"),
        expires_at=link.get("expires_at"),
        ttl_remaining_s=max(0, int(link.get("expires_at", 0) - now_s())),
        downloads=link.get("downloads", 0),
        max_downloads=link.get("max_downloads", 0),
    )


def prune_download_links_locked(
    store: dict[str, Any], now: float | None = None
) -> bool:
    """Remove expired or exhausted download links while STORE_LOCK is held."""
    now = now_s() if now is None else now
    links = store.get("links", {})
    changed = False
    for token, link in list(links.items()):
        expires_at = float(link.get("expires_at", 0))
        max_downloads = int(link.get("max_downloads", 0))
        downloads = int(link.get("downloads", 0))
        if expires_at <= now or (
            max_downloads > 0 and downloads >= max_downloads
        ):
            links.pop(token, None)
            changed = True
    return changed


def create_file_link_execute(
    path: str,
    ttl_s: int | None = None,
    filename: str | None = None,
    max_downloads: int | None = None,
) -> CreateFileLinkOutput:
    """Create a tokenized public download link for one workspace file."""
    settings = get_settings()
    if not settings.file_download_enabled:
        raise PermissionError("file downloads are disabled")

    resolved = resolve_path(path, must_exist=True)
    if not resolved.is_file():
        raise ValueError(f"Not a regular file: {path}")

    size = resolved.stat().st_size
    if (
        settings.file_download_max_file_bytes > 0
        and size > settings.file_download_max_file_bytes
    ):
        raise ValueError(f"File is too large: {size}")

    ttl = coerce_download_ttl(ttl_s)
    limit = coerce_max_downloads(max_downloads)
    token = secrets.token_urlsafe(32)
    created_at = now_s()
    link = {
        "path": str(resolved),
        "display_path": relative_display(resolved),
        "filename": safe_download_filename(filename, resolved),
        "bytes": size,
        "created_at": created_at,
        "expires_at": created_at + ttl,
        "downloads": 0,
        "max_downloads": limit,
    }

    with STORE_LOCK:
        store = read_download_store_locked()
        prune_download_links_locked(store, created_at)
        store["links"][token] = link
        write_download_store_locked(store)

    audit(
        "download_link_created",
        path=link["display_path"],
        token=token,
        expires_at=link["expires_at"],
    )
    return CreateFileLinkOutput.model_validate(
        download_link_summary(token, link).model_dump(mode="json")
    )


def list_file_links_execute(
    include_expired: bool = False,
) -> ListFileLinksOutput:
    """List generated download links."""
    with STORE_LOCK:
        store = read_download_store_locked()
        changed = (
            False if include_expired else prune_download_links_locked(store)
        )
        if changed:
            write_download_store_locked(store)
        links = [
            download_link_summary(token, link)
            for token, link in store.get("links", {}).items()
        ]
    links.sort(key=lambda item: item.get("created_at", 0), reverse=True)
    return ListFileLinksOutput(links=links)


def revoke_file_link_execute(token: str) -> RevokeFileLinkOutput:
    """Revoke one generated download link."""
    with STORE_LOCK:
        store = read_download_store_locked()
        removed = store.get("links", {}).pop(token, None)
        if removed is not None:
            write_download_store_locked(store)
    if removed is not None:
        audit(
            "download_link_revoked",
            path=removed.get("display_path"),
            token=token,
        )
    return RevokeFileLinkOutput(revoked=removed is not None, token=token)


def claim_download(
    token: str, *, consume: bool
) -> tuple[Path, dict[str, Any]] | dict[str, Any]:
    """Return a target path and link metadata, or an error payload."""
    settings = get_settings()
    if not settings.file_download_enabled:
        return {
            "status_code": 404,
            "error": "download_disabled",
            "message": "File downloads are disabled",
        }

    with STORE_LOCK:
        store = read_download_store_locked()
        link = store.get("links", {}).get(token)
        if not link:
            return {
                "status_code": 404,
                "error": "download_not_found",
                "message": "Link not found",
            }

        current_time = now_s()
        if float(link.get("expires_at", 0)) <= current_time:
            store.get("links", {}).pop(token, None)
            write_download_store_locked(store)
            return {
                "status_code": 410,
                "error": "download_expired",
                "message": "Link has expired",
            }

        max_downloads = int(link.get("max_downloads", 0))
        downloads = int(link.get("downloads", 0))
        if max_downloads > 0 and downloads >= max_downloads:
            store.get("links", {}).pop(token, None)
            write_download_store_locked(store)
            return {
                "status_code": 410,
                "error": "download_exhausted",
                "message": "Link has reached its use limit",
            }

        path = Path(str(link.get("path", ""))).resolve(strict=False)
        if not path.exists() or not path.is_file():
            store.get("links", {}).pop(token, None)
            write_download_store_locked(store)
            return {
                "status_code": 404,
                "error": "download_missing",
                "message": "The target file no longer exists",
            }

        if (
            settings.file_download_max_file_bytes > 0
            and path.stat().st_size > settings.file_download_max_file_bytes
        ):
            return {
                "status_code": 403,
                "error": "download_too_large",
                "message": "The target file exceeds the configured size limit",
            }

        if consume:
            link["downloads"] = downloads + 1
            link["last_download_at"] = current_time
            store["links"][token] = link
            write_download_store_locked(store)

    return path, link


create_download_link = create_file_link_execute
list_download_links = list_file_links_execute
revoke_download_link = revoke_file_link_execute
