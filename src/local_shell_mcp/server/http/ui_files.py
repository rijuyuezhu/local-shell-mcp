"""Authenticated Human UI APIs for workspace-confined local files."""

from __future__ import annotations

import asyncio
import base64
import binascii
import mimetypes
import os
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ...config.settings import get_settings
from ...oauth.core.context import MissingOAuthScopeError, require_oauth_scopes
from ...oauth.core.scopes import SCOPE_SHELL_READ, SCOPE_SHELL_WRITE
from ...ops.files import (
    delete_file_or_dir_execute,
    list_files_execute,
    read_file_execute,
    write_file_execute,
)
from ...ops.utils.path import relative_display, resolve_path, workspace_root

UI_FILE_PATH_MAX_BYTES = 4_096
UI_FILE_PREVIEW_MAX_LINES = 400
UI_FILE_DIRECTORY_MAX_ENTRIES = 1_000
UI_FILE_BINARY_PREVIEW_BYTES = 256
UI_FILE_INLINE_IMAGE_TYPES = frozenset(
    {
        "image/avif",
        "image/bmp",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)


def _json_ok(data: Any = None, message: str = "") -> JSONResponse:
    return JSONResponse({"ok": True, "message": message, "data": data})


def _json_error(exc: Exception, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        {
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
        },
        status_code=status_code,
    )


def _require_scopes(*required: str) -> None:
    try:
        require_oauth_scopes(tuple(required))
    except MissingOAuthScopeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _path_arg(value: Any, *, default: str | None = None) -> str:
    path = str(value if value is not None else default or "")
    if not path:
        raise ValueError("path is required")
    if "\x00" in path:
        raise ValueError("path must not contain NUL bytes")
    if len(path.encode("utf-8")) > UI_FILE_PATH_MAX_BYTES:
        raise ValueError(f"path exceeds {UI_FILE_PATH_MAX_BYTES} encoded bytes")
    return path


def _workspace_path(
    path: str,
    *,
    must_exist: bool = False,
    follow_final_symlink: bool = True,
) -> Path:
    """Resolve one path while keeping Human UI access inside workspace even in full-control mode."""
    root = workspace_root()
    raw = Path(os.path.expandvars(os.path.expanduser(path)))
    lexical = Path(
        os.path.abspath(root / raw if not raw.is_absolute() else raw)
    )
    if follow_final_symlink:
        resolved = lexical.resolve(strict=False)
    elif lexical == root:
        resolved = root
    else:
        resolved = lexical.parent.resolve(strict=False) / lexical.name
    boundary = (
        resolved
        if follow_final_symlink or resolved == root
        else resolved.parent
    )
    try:
        boundary.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path escapes workspace: {path}") from exc
    if not follow_final_symlink and resolved == root:
        return resolve_path(str(root), must_exist=must_exist)
    return resolve_path(
        str(resolved),
        must_exist=must_exist,
        follow_final_symlink=follow_final_symlink,
    )


def _entry_payload(entry: Any) -> dict[str, Any]:
    data = entry.model_dump(mode="json")
    path = str(data["path"])
    data["name"] = Path(path).name
    data["hidden"] = data["name"].startswith(".")
    return data


def _sorted_entries(entries: list[Any]) -> list[dict[str, Any]]:
    rows = [_entry_payload(entry) for entry in entries]
    rows.sort(
        key=lambda item: (
            0 if item["type"] == "dir" else 1,
            str(item["name"]).casefold(),
            str(item["name"]),
        )
    )
    return rows


def _list_payload(path: str, *, max_entries: int) -> dict[str, Any]:
    resolved = _workspace_path(path, must_exist=True)
    if not resolved.is_dir():
        raise NotADirectoryError(str(resolved))
    result = list_files_execute(
        str(resolved),
        recursive=False,
        max_entries=min(max_entries, get_settings().max_directory_entries),
    )
    root = workspace_root()
    parent = root if resolved == root else resolved.parent
    return {
        "path": relative_display(resolved),
        "parent": relative_display(parent),
        "count": result.count,
        "limit_count": result.limit_count,
        "is_truncated": result.is_truncated,
        "entries": _sorted_entries(result.entries),
    }


def _looks_binary(sample: bytes) -> bool:
    if b"\x00" in sample:
        return True
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _file_sample(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read(max(4_096, UI_FILE_BINARY_PREVIEW_BYTES))


def _file_preview(path: str) -> dict[str, Any]:
    resolved = _workspace_path(path, must_exist=True)
    if resolved.is_dir():
        return {
            "kind": "directory",
            **_list_payload(
                str(resolved), max_entries=UI_FILE_DIRECTORY_MAX_ENTRIES
            ),
        }
    if not resolved.is_file():
        raise ValueError("Only regular files and directories can be previewed")

    size = resolved.stat().st_size
    media_type = (
        mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    )
    sample = _file_sample(resolved)
    settings = get_settings()
    if media_type in UI_FILE_INLINE_IMAGE_TYPES:
        if size > settings.max_file_read_bytes:
            return {
                "kind": "image",
                "path": relative_display(resolved),
                "bytes": size,
                "media_type": media_type,
                "inline": False,
                "message": (
                    "Image exceeds the configured inline preview limit of "
                    f"{settings.max_file_read_bytes} bytes"
                ),
            }
        data = resolved.read_bytes()
        return {
            "kind": "image",
            "path": relative_display(resolved),
            "bytes": size,
            "media_type": media_type,
            "inline": True,
            "data_base64": base64.b64encode(data).decode("ascii"),
        }

    if _looks_binary(sample):
        return {
            "kind": "binary",
            "path": relative_display(resolved),
            "bytes": size,
            "media_type": media_type,
            "preview_encoding": "hex",
            "preview_bytes": min(len(sample), UI_FILE_BINARY_PREVIEW_BYTES),
            "preview": binascii.hexlify(
                sample[:UI_FILE_BINARY_PREVIEW_BYTES]
            ).decode("ascii"),
        }

    result = read_file_execute(
        str(resolved), start_line=1, end_line=UI_FILE_PREVIEW_MAX_LINES
    )
    payload = result.model_dump(mode="json")
    return {
        "kind": "text",
        **payload,
        "media_type": media_type,
        "preview_truncated": bool(
            result.truncated
            or (
                result.total_lines is not None
                and result.total_lines > UI_FILE_PREVIEW_MAX_LINES
            )
        ),
    }


def _file_content(path: str) -> dict[str, Any]:
    resolved = _workspace_path(path, must_exist=True)
    if not resolved.is_file():
        raise ValueError("Only regular text files can be edited")
    if _looks_binary(_file_sample(resolved)):
        raise ValueError("Binary files cannot be edited in the built-in editor")
    result = read_file_execute(str(resolved))
    if result.truncated:
        raise ValueError(
            "File exceeds the configured editor read limit; use a terminal or external editor"
        )
    return {"kind": "text", **result.model_dump(mode="json")}


def _ensure_mutable_path(path: str, *, follow_final_symlink: bool) -> Path:
    resolved = _workspace_path(
        path,
        must_exist=False,
        follow_final_symlink=follow_final_symlink,
    )
    if resolved == workspace_root():
        raise ValueError("Refusing to mutate the workspace root")
    return resolved


def _write_file(path: str, content: str, overwrite: bool) -> Any:
    resolved = _ensure_mutable_path(path, follow_final_symlink=True)
    return write_file_execute(str(resolved), content, overwrite)


def _delete_file(path: str, recursive: bool) -> Any:
    resolved = _ensure_mutable_path(path, follow_final_symlink=False)
    return delete_file_or_dir_execute(str(resolved), recursive)


async def api_files(request: Request) -> Response:
    """List one bounded local workspace directory for the Human UI."""
    _require_scopes(SCOPE_SHELL_READ)
    try:
        path = _path_arg(request.query_params.get("path"), default=".")
        payload = await asyncio.to_thread(
            _list_payload, path, max_entries=UI_FILE_DIRECTORY_MAX_ENTRIES
        )
        return _json_ok(payload)
    except Exception as exc:
        return _json_error(exc)


async def api_file_preview(request: Request) -> Response:
    """Return a bounded directory, text, binary, or inline image preview."""
    _require_scopes(SCOPE_SHELL_READ)
    try:
        path = _path_arg(request.query_params.get("path"))
        return _json_ok(await asyncio.to_thread(_file_preview, path))
    except Exception as exc:
        return _json_error(exc)


async def api_file_content(request: Request) -> Response:
    """Return one complete bounded UTF-8 file for the built-in editor."""
    _require_scopes(SCOPE_SHELL_READ)
    try:
        path = _path_arg(request.query_params.get("path"))
        return _json_ok(await asyncio.to_thread(_file_content, path))
    except Exception as exc:
        return _json_error(exc)


async def api_file_action(request: Request) -> Response:
    """Create, replace, or delete a local workspace file through existing safe primitives."""
    _require_scopes(SCOPE_SHELL_READ, SCOPE_SHELL_WRITE)
    action = str(request.path_params.get("action") or "")
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object")
        path = _path_arg(body.get("path"))
        if action == "write":
            content = body.get("content")
            if not isinstance(content, str):
                raise ValueError("content must be a string")
            result = await asyncio.to_thread(
                _write_file,
                path,
                content,
                bool(body.get("overwrite", True)),
            )
        elif action == "delete":
            result = await asyncio.to_thread(
                _delete_file,
                path,
                bool(body.get("recursive", False)),
            )
        else:
            raise ValueError(f"Unsupported file action: {action}")
        return _json_ok(result.model_dump(mode="json"))
    except HTTPException:
        raise
    except Exception as exc:
        return _json_error(exc)
