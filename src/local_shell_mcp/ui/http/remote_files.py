"""Remote-worker file helpers for the authenticated Human UI."""

import asyncio
import base64
import binascii
import codecs
import hashlib
import mimetypes
import re
import threading
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, cast

from ...config.settings import get_settings
from ...ops.utils.remote_session import start_worker_session
from ...remote.manager import remote_manager
from ...remote.service import call_remote_worker_tool
from ...remote.tool_specs import (
    REMOTE_WORKER_ORIGIN_ARG,
    REMOTE_WORKER_ORIGIN_HUMAN_UI,
)
from ...schemas.result_models.files import ListFilesOutput
from ...schemas.result_models.transfer import (
    TransferReadChunkOutput,
    TransferStatOutput,
)
from .common import sorted_entry_payloads
from .image_preview import UiImagePreviewRequest, terminal_image_fields

UI_REMOTE_FILE_TIMEOUT_S = 60
UI_REMOTE_FILE_SAMPLE_BYTES = 4_096
UI_REMOTE_FILE_BINARY_PREVIEW_BYTES = 256
UI_REMOTE_FILE_PREVIEW_MAX_LINES = 400
UI_REMOTE_FILE_DIRECTORY_MAX_ENTRIES = 1_000
UI_REMOTE_FILE_CHUNK_BYTES = 256 * 1024
UI_REMOTE_FILE_LOCK_SHARDS = 64
UI_REMOTE_INLINE_IMAGE_TYPES = frozenset(
    {
        "image/avif",
        "image/bmp",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)
_DRIVE_PATH = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True)
class _RemoteFileSession:
    machine: str
    workdir: str
    worker_session_id: str


_SESSION_CACHE: dict[str, _RemoteFileSession] = {}
_SESSION_CACHE_LOCK = threading.Lock()
_MACHINE_LOCKS = tuple(
    threading.Lock() for _ in range(UI_REMOTE_FILE_LOCK_SHARDS)
)


def clear_ui_remote_file_sessions() -> None:
    """Clear cached worker sessions. Intended for tests and process reset hooks."""
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE.clear()


def _machine_lock(machine: str) -> threading.Lock:
    digest = hashlib.sha256(machine.encode("utf-8")).digest()
    shard = int.from_bytes(digest[:2], "big") % len(_MACHINE_LOCKS)
    return _MACHINE_LOCKS[shard]


async def _acquire_machine_lock(machine: str) -> threading.Lock:
    lock = _machine_lock(machine)
    while not lock.acquire(blocking=False):
        await asyncio.sleep(0.01)
    return lock


def normalize_remote_ui_path(path: str) -> str:
    """Return one portable workspace-relative path for the remote Files UI."""
    normalized = str(path).replace("\\", "/")
    if not normalized:
        raise ValueError("path is required")
    if "\x00" in normalized:
        raise ValueError("path must not contain NUL bytes")
    if normalized.startswith(("/", "//")) or _DRIVE_PATH.match(normalized):
        raise ValueError("Remote Files paths must be workspace-relative")
    if normalized.split("/", 1)[0].startswith("~"):
        raise ValueError("Remote Files paths must not use home expansion")
    parts: list[str] = []
    for part in normalized.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise ValueError("Remote Files paths must not contain '..'")
        parts.append(part)
    return "/".join(parts) or "."


def remote_ui_parent(path: str) -> str:
    """Return the portable parent path for one normalized remote UI path."""
    normalized = normalize_remote_ui_path(path)
    if normalized == ".":
        return "."
    parent = str(PurePosixPath(normalized).parent)
    return "." if parent in {"", "."} else parent


def _remote_machine(machine: str) -> tuple[str, str]:
    """Validate one online remote worker and return its name/workdir."""
    settings = get_settings()
    if not settings.remote_enabled:
        raise ValueError("Remote workers are disabled")
    if not machine or machine == "local":
        raise ValueError("A remote machine name is required")
    inventory = remote_manager().list_machines()
    row = next(
        (item for item in inventory.machines if item.name == machine), None
    )
    if row is None:
        with _SESSION_CACHE_LOCK:
            _SESSION_CACHE.pop(machine, None)
        raise ValueError(f"Unknown remote machine: {machine}")
    if row.status != "online":
        with _SESSION_CACHE_LOCK:
            _SESSION_CACHE.pop(machine, None)
        raise ConnectionError(f"Remote machine {machine} is {row.status}")
    return row.name, str(row.workdir or ".")


def _remote_timeout_s() -> int:
    return max(
        1,
        min(int(get_settings().remote_job_timeout_s), UI_REMOTE_FILE_TIMEOUT_S),
    )


def _remote_result_data(
    result: dict[str, Any], *, machine: str, tool: str
) -> dict[str, Any]:
    if not result.get("ok", False):
        raise RuntimeError(
            str(result.get("message") or f"remote {tool} failed on {machine}")
        )
    data = result.get("data")
    if isinstance(data, dict) and data.get("status") == "error":
        error_type = str(data.get("error_type") or "remote_error")
        message = str(
            data.get("message") or f"remote {tool} failed on {machine}"
        )
        raise RuntimeError(f"{error_type}: {message}")
    if isinstance(data, dict):
        return cast(dict[str, Any], data)
    return {"result": data}


def _cached_session(machine: str, workdir: str) -> _RemoteFileSession | None:
    with _SESSION_CACHE_LOCK:
        cached = _SESSION_CACHE.get(machine)
        if cached is None or cached.workdir != workdir:
            return None
        return cached


async def _remote_file_session(machine: str) -> _RemoteFileSession:
    machine, workdir = _remote_machine(machine)
    cached = _cached_session(machine, workdir)
    if cached is not None:
        return cached

    lock = await _acquire_machine_lock(machine)
    try:
        cached = _cached_session(machine, workdir)
        if cached is not None:
            return cached
        created = await start_worker_session(
            machine=machine,
            workdir=workdir,
            label="Human UI Workspace",
            timeout_s=_remote_timeout_s(),
        )
        worker_session_id = str(created.get("session_id") or "")
        if not worker_session_id:
            raise RuntimeError(
                f"Remote machine {machine} returned no file workspace session"
            )
        session = _RemoteFileSession(
            machine=machine,
            workdir=workdir,
            worker_session_id=worker_session_id,
        )
        with _SESSION_CACHE_LOCK:
            _SESSION_CACHE[machine] = session
        return session
    finally:
        lock.release()


def _invalidate_session(machine: str, worker_session_id: str) -> None:
    with _SESSION_CACHE_LOCK:
        cached = _SESSION_CACHE.get(machine)
        if cached is not None and cached.worker_session_id == worker_session_id:
            _SESSION_CACHE.pop(machine, None)


def _missing_worker_session(exc: Exception) -> bool:
    message = str(exc).casefold()
    return (
        "unknown session_id" in message or "call session_start first" in message
    )


async def call_remote_ui_workspace_tool(
    machine: str,
    tool: str,
    args: dict[str, Any],
    *,
    retry_session: bool = True,
) -> dict[str, Any]:
    """Call one session-bound remote UI tool, recreating stale sessions once."""
    session = await _remote_file_session(machine)
    payload = {
        **args,
        "session_id": session.worker_session_id,
        REMOTE_WORKER_ORIGIN_ARG: REMOTE_WORKER_ORIGIN_HUMAN_UI,
    }
    timeout_s = _remote_timeout_s()
    try:
        result = await call_remote_worker_tool(
            machine, tool, payload, timeout_s
        )
        return _remote_result_data(result, machine=machine, tool=tool)
    except Exception as exc:
        if not retry_session or not _missing_worker_session(exc):
            raise
        _invalidate_session(machine, session.worker_session_id)
        return await call_remote_ui_workspace_tool(
            machine,
            tool,
            args,
            retry_session=False,
        )


call_remote_ui_file_tool = call_remote_ui_workspace_tool


def _entry_payload(entry: Any) -> dict[str, Any]:
    data = entry.model_dump(mode="json")
    path = normalize_remote_ui_path(str(data["path"]))
    data["path"] = path
    data["name"] = PurePosixPath(path).name
    data["hidden"] = data["name"].startswith(".")
    return data


async def remote_list_payload(machine: str, path: str) -> dict[str, Any]:
    """Return one bounded directory listing from a remote worker session."""
    normalized = normalize_remote_ui_path(path)
    result = ListFilesOutput.model_validate(
        await call_remote_ui_file_tool(
            machine,
            "list_files",
            {
                "path": normalized,
                "recursive": False,
                "max_entries": UI_REMOTE_FILE_DIRECTORY_MAX_ENTRIES,
            },
        )
    )
    return {
        "machine": machine,
        "remote": True,
        "path": normalized,
        "parent": remote_ui_parent(normalized),
        "count": result.count,
        "limit_count": result.limit_count,
        "is_truncated": result.is_truncated,
        "entries": sorted_entry_payloads(result.entries, _entry_payload),
        "mutations": {
            "write": True,
            "delete": True,
            "copy": False,
            "move": False,
            "rename": False,
            "mkdir": False,
        },
    }


def _looks_binary(sample: bytes, *, complete: bool) -> bool:
    if b"\x00" in sample:
        return True
    try:
        _decode_remote_text(sample, complete=complete)
    except UnicodeDecodeError:
        return True
    return False


async def _remote_chunk(
    machine: str, path: str, offset: int, chunk_size: int
) -> TransferReadChunkOutput:
    return TransferReadChunkOutput.model_validate(
        await call_remote_ui_file_tool(
            machine,
            "transfer_read_chunk",
            {"path": path, "offset": offset, "chunk_size": chunk_size},
        )
    )


async def _remote_bytes(
    machine: str,
    path: str,
    size: int,
    *,
    limit: int | None = None,
) -> bytes:
    target = size if limit is None else min(size, max(0, limit))
    if target == 0:
        return b""
    chunks: list[bytes] = []
    offset = 0
    while offset < target:
        requested = min(UI_REMOTE_FILE_CHUNK_BYTES, target - offset)
        chunk = await _remote_chunk(machine, path, offset, requested)
        data = base64.b64decode(chunk.data_b64, validate=True)
        digest = hashlib.sha256(data).hexdigest()
        if (
            len(data) != chunk.bytes
            or chunk.offset != offset
            or chunk.size != size
            or len(data) > requested
            or chunk.sha256 != digest
        ):
            raise RuntimeError(
                "Remote file chunk metadata did not match its payload"
            )
        chunks.append(data)
        offset += len(data)
        if offset < target and chunk.eof:
            raise RuntimeError("Remote file changed while it was being read")
        if not data:
            raise RuntimeError("Remote file transfer made no progress")
    payload = b"".join(chunks)
    if len(payload) != target:
        raise RuntimeError(
            f"Remote file changed while being read: expected {target} bytes, received {len(payload)}"
        )
    return payload


def _decode_remote_text(data: bytes, *, complete: bool) -> str:
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    return decoder.decode(data, final=complete)


def _binary_preview(
    machine: str,
    path: str,
    size: int,
    media_type: str,
    sample: bytes,
) -> dict[str, Any]:
    return {
        "kind": "binary",
        "machine": machine,
        "remote": True,
        "path": path,
        "bytes": size,
        "media_type": media_type,
        "preview_encoding": "hex",
        "preview_bytes": min(len(sample), UI_REMOTE_FILE_BINARY_PREVIEW_BYTES),
        "preview": binascii.hexlify(
            sample[:UI_REMOTE_FILE_BINARY_PREVIEW_BYTES]
        ).decode("ascii"),
    }


async def remote_file_preview(
    machine: str,
    path: str,
    preview_request: UiImagePreviewRequest | None = None,
) -> dict[str, Any]:
    """Return a bounded remote directory, text, binary, or inline image preview."""
    normalized = normalize_remote_ui_path(path)
    metadata = TransferStatOutput.model_validate(
        await call_remote_ui_file_tool(
            machine,
            "transfer_stat",
            {"path": normalized, "sha256": False},
        )
    )
    if metadata.type == "dir":
        return {
            "kind": "directory",
            **await remote_list_payload(machine, normalized),
        }
    if metadata.type != "file" or metadata.size is None:
        raise ValueError("Only regular files and directories can be previewed")

    size = int(metadata.size)
    media_type = (
        mimetypes.guess_type(PurePosixPath(normalized).name)[0]
        or "application/octet-stream"
    )
    sample = await _remote_bytes(
        machine,
        normalized,
        size,
        limit=max(
            UI_REMOTE_FILE_SAMPLE_BYTES, UI_REMOTE_FILE_BINARY_PREVIEW_BYTES
        ),
    )
    settings = get_settings()
    if media_type in UI_REMOTE_INLINE_IMAGE_TYPES:
        if size > settings.max_file_read_bytes:
            return {
                "kind": "image",
                "machine": machine,
                "remote": True,
                "path": normalized,
                "bytes": size,
                "media_type": media_type,
                "inline": False,
                "message": (
                    "Image exceeds the configured inline preview limit of "
                    f"{settings.max_file_read_bytes} bytes"
                ),
            }
        data = await _remote_bytes(machine, normalized, size)

        return {
            "kind": "image",
            "machine": machine,
            "remote": True,
            "path": normalized,
            "bytes": size,
            "media_type": media_type,
            "inline": True,
            "data_base64": base64.b64encode(data).decode("ascii"),
            **terminal_image_fields(data, preview_request),
        }

    if _looks_binary(sample, complete=len(sample) == size):
        return _binary_preview(machine, normalized, size, media_type, sample)

    data = await _remote_bytes(
        machine,
        normalized,
        size,
        limit=settings.max_file_read_bytes,
    )
    complete = len(data) == size
    try:
        content = _decode_remote_text(data, complete=complete)
    except UnicodeDecodeError:
        return _binary_preview(machine, normalized, size, media_type, sample)
    lines = content.splitlines(keepends=True)
    preview_lines = lines[:UI_REMOTE_FILE_PREVIEW_MAX_LINES]
    preview_content = "".join(preview_lines)
    preview_truncated = not complete or len(lines) > len(preview_lines)
    return {
        "kind": "text",
        "machine": machine,
        "remote": True,
        "path": normalized,
        "bytes": size,
        "bytes_read": len(data),
        "truncated_bytes": size - len(data),
        "total_lines": len(lines) if complete else None,
        "start_line": 1 if preview_lines else None,
        "end_line": len(preview_lines) if preview_lines else None,
        "line_count": len(preview_lines),
        "truncated": not complete,
        "content": preview_content,
        "media_type": media_type,
        "preview_truncated": preview_truncated,
    }


async def remote_file_content(machine: str, path: str) -> dict[str, Any]:
    """Return one complete bounded UTF-8 remote file for the built-in editor."""
    normalized = normalize_remote_ui_path(path)
    metadata = TransferStatOutput.model_validate(
        await call_remote_ui_file_tool(
            machine,
            "transfer_stat",
            {"path": normalized, "sha256": False},
        )
    )
    if metadata.type != "file" or metadata.size is None:
        raise ValueError("Only regular text files can be edited")
    size = int(metadata.size)
    limit = get_settings().max_file_read_bytes
    if size > limit:
        raise ValueError(
            "File exceeds the configured editor read limit; use a remote terminal or external editor"
        )
    data = await _remote_bytes(machine, normalized, size)
    sample = data[:UI_REMOTE_FILE_SAMPLE_BYTES]
    if _looks_binary(sample, complete=len(sample) == len(data)):
        raise ValueError("Binary files cannot be edited in the built-in editor")
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "Binary files cannot be edited in the built-in editor"
        ) from exc
    lines = content.splitlines()

    return {
        "kind": "text",
        "machine": machine,
        "remote": True,
        "path": normalized,
        "bytes": size,
        "bytes_read": size,
        "truncated_bytes": 0,
        "total_lines": len(lines),
        "start_line": 1 if lines else None,
        "end_line": len(lines) if lines else None,
        "line_count": len(lines),
        "truncated": False,
        "content": content,
        "file_sha256": hashlib.sha256(data).hexdigest(),
    }


async def remote_write_file(
    machine: str,
    path: str,
    content: str,
    overwrite: bool,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Create or atomically replace one remote workspace text file."""
    normalized = normalize_remote_ui_path(path)
    return await call_remote_ui_file_tool(
        machine,
        "write_file",
        {
            "path": normalized,
            "content": content,
            "overwrite": overwrite,
            "expected_sha256": expected_sha256,
        },
    )


async def remote_delete_file(
    machine: str, path: str, recursive: bool
) -> dict[str, Any]:
    """Delete one remote workspace entry through the existing safe primitive."""
    normalized = normalize_remote_ui_path(path)
    if normalized == ".":
        raise ValueError("Refusing to mutate the remote workspace root")
    return await call_remote_ui_file_tool(
        machine,
        "delete_file_or_dir",
        {"path": normalized, "recursive": recursive},
    )
