from __future__ import annotations

import json
import mimetypes
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from .audit import audit
from .fs_ops import relative_display, resolve_path
from .settings import get_settings

_DOWNLOAD_PREFIX = "/download"
_DOWNLOAD_STORE_VERSION = 1
_STORE_LOCK = threading.RLock()


def _now() -> float:
    return time.time()


def _store_path() -> Path:
    settings = get_settings()
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    return settings.state_dir / "downloads.json"


def _empty_store() -> dict[str, Any]:
    return {"version": _DOWNLOAD_STORE_VERSION, "links": {}}


def _read_store_locked() -> dict[str, Any]:
    path = _store_path()
    if not path.exists():
        return _empty_store()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        audit("download_store_unreadable", path=str(path))
        return _empty_store()
    if not isinstance(data, dict) or not isinstance(data.get("links"), dict):
        return _empty_store()
    data.setdefault("version", _DOWNLOAD_STORE_VERSION)
    return data


def _write_store_locked(store: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp-{os.getpid()}-{secrets.token_hex(4)}")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _public_base_url() -> str:
    settings = get_settings()
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    host = settings.host
    if host in {"", "0.0.0.0", "::"}:
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{settings.port}"


def _coerce_ttl(ttl_s: int | None) -> int:
    settings = get_settings()
    requested = settings.file_download_default_ttl_s if ttl_s is None else int(ttl_s)
    if requested <= 0:
        raise ValueError("ttl_s must be positive")
    return min(requested, settings.file_download_max_ttl_s)


def _coerce_max_downloads(max_downloads: int | None) -> int:
    settings = get_settings()
    requested = settings.file_download_default_max_downloads if max_downloads is None else int(max_downloads)
    if requested < 0:
        raise ValueError("max_downloads must be >= 0; use 0 for unlimited")
    return requested


def _safe_filename(filename: str | None, source: Path) -> str:
    candidate = Path(filename).name if filename else source.name
    candidate = candidate.strip().replace("\x00", "")
    return candidate or "download"


def _link_summary(token: str, link: dict[str, Any]) -> dict[str, Any]:
    return {
        "token": token,
        "url": f"{_public_base_url()}{_DOWNLOAD_PREFIX}/{token}",
        "path": link.get("display_path"),
        "filename": link.get("filename"),
        "bytes": link.get("bytes"),
        "created_at": link.get("created_at"),
        "expires_at": link.get("expires_at"),
        "ttl_remaining_s": max(0, int(link.get("expires_at", 0) - _now())),
        "downloads": link.get("downloads", 0),
        "max_downloads": link.get("max_downloads", 0),
    }


def _prune_locked(store: dict[str, Any], now: float | None = None) -> bool:
    now = _now() if now is None else now
    links = store.get("links", {})
    changed = False
    for token, link in list(links.items()):
        expires_at = float(link.get("expires_at", 0))
        max_downloads = int(link.get("max_downloads", 0))
        downloads = int(link.get("downloads", 0))
        if expires_at <= now or (max_downloads > 0 and downloads >= max_downloads):
            links.pop(token, None)
            changed = True
    return changed


def create_share_link(
    path: str,
    ttl_s: int | None = None,
    filename: str | None = None,
    max_downloads: int | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.file_download_enabled:
        raise PermissionError("disabled")

    resolved = resolve_path(path, must_exist=True)
    if not resolved.is_file():
        raise ValueError(f"Not a regular file: {path}")

    size = resolved.stat().st_size
    if settings.file_download_max_file_bytes > 0 and size > settings.file_download_max_file_bytes:
        raise ValueError(f"File is too large: {size}")

    ttl = _coerce_ttl(ttl_s)
    limit = _coerce_max_downloads(max_downloads)
    token = secrets.token_urlsafe(32)
    now = _now()
    link = {
        "path": str(resolved),
        "display_path": relative_display(resolved),
        "filename": _safe_filename(filename, resolved),
        "bytes": size,
        "created_at": now,
        "expires_at": now + ttl,
        "downloads": 0,
        "max_downloads": limit,
    }

    with _STORE_LOCK:
        store = _read_store_locked()
        _prune_locked(store, now)
        store["links"][token] = link
        _write_store_locked(store)

    audit("download_link_created", path=link["display_path"], token=token, expires_at=link["expires_at"])
    return _link_summary(token, link)


def list_share_links(include_expired: bool = False) -> dict[str, Any]:
    with _STORE_LOCK:
        store = _read_store_locked()
        changed = False if include_expired else _prune_locked(store)
        if changed:
            _write_store_locked(store)
        links = [_link_summary(token, link) for token, link in store.get("links", {}).items()]
    links.sort(key=lambda item: item.get("created_at", 0), reverse=True)
    return {"links": links}


def revoke_share_link(token: str) -> dict[str, Any]:
    with _STORE_LOCK:
        store = _read_store_locked()
        removed = store.get("links", {}).pop(token, None)
        if removed is not None:
            _write_store_locked(store)
    if removed is not None:
        audit("download_link_revoked", path=removed.get("display_path"), token=token)
    return {"revoked": removed is not None, "token": token}


def _error_response(status_code: int, error: str, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": error, "message": message}, status_code=status_code)


def _claim_download(token: str, *, consume: bool) -> tuple[Path, dict[str, Any]] | Response:
    settings = get_settings()
    if not settings.file_download_enabled:
        return _error_response(404, "download_disabled", "File downloads are disabled")

    with _STORE_LOCK:
        store = _read_store_locked()
        link = store.get("links", {}).get(token)
        if not link:
            return _error_response(404, "download_not_found", "Link not found")

        now = _now()
        if float(link.get("expires_at", 0)) <= now:
            store.get("links", {}).pop(token, None)
            _write_store_locked(store)
            return _error_response(410, "download_expired", "Link has expired")

        max_downloads = int(link.get("max_downloads", 0))
        downloads = int(link.get("downloads", 0))
        if max_downloads > 0 and downloads >= max_downloads:
            store.get("links", {}).pop(token, None)
            _write_store_locked(store)
            return _error_response(410, "download_exhausted", "Link has reached its use limit")

        path = Path(str(link.get("path", ""))).resolve(strict=False)
        if not path.exists() or not path.is_file():
            store.get("links", {}).pop(token, None)
            _write_store_locked(store)
            return _error_response(404, "download_missing", "The target file no longer exists")

        if settings.file_download_max_file_bytes > 0 and path.stat().st_size > settings.file_download_max_file_bytes:
            return _error_response(403, "download_too_large", "The target file exceeds the configured size limit")

        if consume:
            link["downloads"] = downloads + 1
            link["last_download_at"] = now
            store["links"][token] = link
            _write_store_locked(store)

    return path, link


async def download_endpoint(request: Request) -> Response:
    token = request.path_params.get("token", "")
    claimed = _claim_download(token, consume=request.method.upper() == "GET")
    if isinstance(claimed, Response):
        return claimed

    path, link = claimed
    media_type = mimetypes.guess_type(link.get("filename") or path.name)[0] or "application/octet-stream"
    audit("download_link_served", path=link.get("display_path"), token=token, method=request.method)
    return FileResponse(
        path,
        media_type=media_type,
        filename=link.get("filename") or path.name,
        headers={"Cache-Control": "private, no-store"},
    )


def download_routes() -> list[Route]:
    return [Route(f"{_DOWNLOAD_PREFIX}/{{token}}", download_endpoint, methods=["GET", "HEAD"])]


create_download_link = create_share_link
list_download_links = list_share_links
revoke_download_link = revoke_share_link
