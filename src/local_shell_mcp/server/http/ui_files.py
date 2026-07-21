"""Authenticated Human UI APIs for workspace-confined local files."""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import errno
import mimetypes
import os
import shutil
import stat
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ...config.settings import get_settings
from ...oauth.core.context import MissingOAuthScopeError, require_oauth_scopes
from ...oauth.core.scopes import (
    SCOPE_REMOTE_USE,
    SCOPE_SHELL_READ,
    SCOPE_SHELL_WRITE,
)
from ...ops.files import (
    delete_file_or_dir_execute,
    list_files_execute,
    read_file_execute,
    write_file_execute,
)
from ...ops.utils.path import relative_display, resolve_path, workspace_root
from ...utils.path_locks import path_locks
from .ui_remote_files import (
    remote_delete_file,
    remote_file_content,
    remote_file_preview,
    remote_list_payload,
    remote_write_file,
)

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


def _machine_arg(value: Any) -> str:
    machine = str(value or "local").strip()
    if not machine:
        return "local"
    if len(machine.encode("utf-8")) > 255:
        raise ValueError("machine exceeds 255 encoded bytes")
    return machine


def _require_file_scopes(machine: str, *, write: bool = False) -> None:
    required = [SCOPE_SHELL_READ]
    if write:
        required.append(SCOPE_SHELL_WRITE)
    if machine != "local":
        required.append(SCOPE_REMOTE_USE)
    _require_scopes(*required)


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
        "machine": "local",
        "remote": False,
        "path": relative_display(resolved),
        "parent": relative_display(parent),
        "count": result.count,
        "limit_count": result.limit_count,
        "is_truncated": result.is_truncated,
        "entries": _sorted_entries(result.entries),
        "mutations": {
            "write": True,
            "delete": True,
            "copy": True,
            "move": True,
            "rename": True,
        },
    }


def _looks_binary(sample: bytes, *, continuation: bytes = b"") -> bool:
    if b"\x00" in sample:
        return True
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError as exc:
        if exc.reason != "unexpected end of data" or exc.end != len(sample):
            return True
        lead = sample[exc.start]
        if lead < 0xC2 or lead > 0xF4:
            return True
        width = 2 if lead < 0xE0 else 3 if lead < 0xF0 else 4
        missing = width - (len(sample) - exc.start)
        sequence = sample[exc.start :] + continuation[:missing]
        if len(sequence) != width:
            return True
        try:
            sequence.decode("utf-8")
        except UnicodeDecodeError:
            return True
    return False


def _file_sample(path: Path) -> tuple[bytes, bytes]:
    sample_bytes = max(4_096, UI_FILE_BINARY_PREVIEW_BYTES)
    with path.open("rb") as handle:
        probe = handle.read(sample_bytes + 3)
    return probe[:sample_bytes], probe[sample_bytes:]


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
    sample, continuation = _file_sample(resolved)
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

    if _looks_binary(sample, continuation=continuation):
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
    sample, continuation = _file_sample(resolved)
    if _looks_binary(sample, continuation=continuation):
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


def _source_entry(path: str) -> Path:
    resolved = _workspace_path(
        path,
        must_exist=True,
        follow_final_symlink=False,
    )
    if resolved == workspace_root():
        raise ValueError("Refusing to mutate the workspace root")
    return resolved


def _destination_entry(path: str) -> Path:
    resolved = _ensure_mutable_path(path, follow_final_symlink=False)
    if not resolved.parent.is_dir():
        raise NotADirectoryError(str(resolved.parent))
    return resolved


def _entry_kind(path: Path) -> str:
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        return "link"
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "dir"
    raise ValueError(
        "Only regular files, directories, and symbolic links can be copied or moved"
    )


def _validate_copy_destination(
    source: Path, destination: Path, kind: str
) -> None:
    if source == destination:
        raise ValueError("Source and destination must be different")
    if os.path.lexists(destination):
        raise FileExistsError(str(destination))
    if kind == "dir":
        try:
            destination.relative_to(source)
        except ValueError:
            pass
        else:
            raise ValueError(
                "A directory cannot be copied or moved inside itself"
            )


def _remove_entry(path: Path) -> None:
    if not os.path.lexists(path):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _copy_regular_file(source: Path, destination: Path) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_BINARY", 0)
    with source.open("rb") as input_handle:
        before = os.fstat(input_handle.fileno())
        fd = os.open(destination, flags, stat.S_IMODE(before.st_mode))
        try:
            with os.fdopen(fd, "wb") as output_handle:
                shutil.copyfileobj(
                    input_handle, output_handle, length=1024 * 1024
                )
                output_handle.flush()
                os.fsync(output_handle.fileno())
            after = os.fstat(input_handle.fileno())
            signature_before = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            )
            signature_after = (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
            if signature_before != signature_after:
                raise RuntimeError(
                    "Source file changed while it was being copied"
                )
            shutil.copystat(source, destination, follow_symlinks=False)
        except BaseException:
            _remove_entry(destination)
            raise


def _copy_entry_locked(source: Path, destination: Path, kind: str) -> None:
    if kind == "file":
        _copy_regular_file(source, destination)
        return
    if kind == "link":
        target = os.readlink(source)
        try:
            os.symlink(
                target,
                destination,
                target_is_directory=source.resolve(strict=False).is_dir(),
            )
            with contextlib.suppress(OSError):
                shutil.copystat(source, destination, follow_symlinks=False)
        except BaseException:
            _remove_entry(destination)
            raise
        return
    try:
        shutil.copytree(
            source,
            destination,
            symlinks=True,
            copy_function=shutil.copy2,
        )
    except BaseException:
        _remove_entry(destination)
        raise


def _copy_entry(source_path: str, destination_path: str) -> dict[str, Any]:
    source = _source_entry(source_path)
    destination = _destination_entry(destination_path)
    with path_locks([source, destination]):
        if not os.path.lexists(source):
            raise FileNotFoundError(str(source))
        kind = _entry_kind(source)
        _validate_copy_destination(source, destination, kind)
        _copy_entry_locked(source, destination, kind)
    return {
        "action": "copy",
        "source": relative_display(source),
        "destination": relative_display(destination),
        "type": kind,
    }


def _move_entry(
    source_path: str,
    destination_path: str,
    *,
    action: str = "move",
) -> dict[str, Any]:
    source = _source_entry(source_path)
    destination = _destination_entry(destination_path)
    with path_locks([source, destination]):
        if not os.path.lexists(source):
            raise FileNotFoundError(str(source))
        kind = _entry_kind(source)
        _validate_copy_destination(source, destination, kind)
        try:
            os.rename(source, destination)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            _copy_entry_locked(source, destination, kind)
            try:
                _remove_entry(source)
            except BaseException:
                _remove_entry(destination)
                raise
    return {
        "action": action,
        "source": relative_display(source),
        "destination": relative_display(destination),
        "type": kind,
    }


def _rename_entry(path: str, name: str) -> dict[str, Any]:
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("name must be one file name without path separators")
    if len(name.encode("utf-8")) > 255:
        raise ValueError("name exceeds 255 encoded bytes")
    source = _source_entry(path)
    return _move_entry(
        str(source),
        str(source.with_name(name)),
        action="rename",
    )


def _write_file(path: str, content: str, overwrite: bool) -> Any:
    resolved = _ensure_mutable_path(path, follow_final_symlink=True)
    return write_file_execute(str(resolved), content, overwrite)


def _delete_file(path: str, recursive: bool) -> Any:
    resolved = _ensure_mutable_path(path, follow_final_symlink=False)
    return delete_file_or_dir_execute(str(resolved), recursive)


async def api_files(request: Request) -> Response:
    """List one bounded local or remote workspace directory for the Human UI."""
    try:
        machine = _machine_arg(request.query_params.get("machine"))
        _require_file_scopes(machine)
        path = _path_arg(request.query_params.get("path"), default=".")
        if machine == "local":
            payload = await asyncio.to_thread(
                _list_payload,
                path,
                max_entries=UI_FILE_DIRECTORY_MAX_ENTRIES,
            )
        else:
            payload = await remote_list_payload(machine, path)
        return _json_ok(payload)
    except HTTPException:
        raise
    except Exception as exc:
        return _json_error(exc)


async def api_file_preview(request: Request) -> Response:
    """Return a bounded local or remote directory, text, binary, or image preview."""
    try:
        machine = _machine_arg(request.query_params.get("machine"))
        _require_file_scopes(machine)
        path = _path_arg(request.query_params.get("path"))
        payload = (
            await asyncio.to_thread(_file_preview, path)
            if machine == "local"
            else await remote_file_preview(machine, path)
        )
        return _json_ok(payload)
    except HTTPException:
        raise
    except Exception as exc:
        return _json_error(exc)


async def api_file_content(request: Request) -> Response:
    """Return one complete bounded local or remote UTF-8 file for editing."""
    try:
        machine = _machine_arg(request.query_params.get("machine"))
        _require_file_scopes(machine)
        path = _path_arg(request.query_params.get("path"))
        payload = (
            await asyncio.to_thread(_file_content, path)
            if machine == "local"
            else await remote_file_content(machine, path)
        )
        return _json_ok(payload)
    except HTTPException:
        raise
    except Exception as exc:
        return _json_error(exc)


async def api_file_action(request: Request) -> Response:
    """Mutate local or remote workspace entries through safe file primitives."""
    action = str(request.path_params.get("action") or "")
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object")
        machine = _machine_arg(body.get("machine"))
        _require_file_scopes(machine, write=True)
        path = _path_arg(body.get("path"))
        if machine != "local":
            if action == "write":
                content = body.get("content")
                if not isinstance(content, str):
                    raise ValueError("content must be a string")
                result = await remote_write_file(
                    machine,
                    path,
                    content,
                    bool(body.get("overwrite", True)),
                )
            elif action == "delete":
                result = await remote_delete_file(
                    machine,
                    path,
                    bool(body.get("recursive", False)),
                )
            else:
                raise ValueError(
                    f"Remote Files does not support {action}; use a remote terminal"
                )
        elif action == "write":
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
        elif action in {"copy", "move"}:
            destination = _path_arg(body.get("destination"))
            operation = _copy_entry if action == "copy" else _move_entry
            result = await asyncio.to_thread(operation, path, destination)
        elif action == "rename":
            name = body.get("name")
            if not isinstance(name, str):
                raise ValueError("name must be a string")
            result = await asyncio.to_thread(_rename_entry, path, name.strip())
        else:
            raise ValueError(f"Unsupported file action: {action}")
        payload = (
            result
            if isinstance(result, dict)
            else result.model_dump(mode="json")
        )
        if isinstance(payload, dict):
            payload.setdefault("machine", machine)
            payload.setdefault("remote", machine != "local")
        return _json_ok(payload)
    except HTTPException:
        raise
    except Exception as exc:
        return _json_error(exc)
