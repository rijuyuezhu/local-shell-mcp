"""High-level remote file and directory transfer helpers."""

import asyncio
from contextlib import suppress
from typing import Any

from ..ops.files_ops import delete_file_or_dir_execute
from ..ops.transfer_ops import (
    normalize_chunk_size,
    transfer_abort_write,
    transfer_alloc_temp_path,
    transfer_begin_write,
    transfer_finish_write,
    transfer_pack_dir,
    transfer_read_chunk,
    transfer_stat,
    transfer_unpack_archive,
    transfer_write_chunk,
)
from ..schemas.result_models.remote import (
    RemoteCopyDirOutput,
    RemoteCopyFileOutput,
)
from ..tools.serialization import tool_output_jsonable
from .service import call_remote_worker_tool


class RemoteTransferError(RuntimeError):
    """Raised when a remote worker transfer primitive reports failure."""


def _unwrap_remote_transfer_result(
    result: dict[str, Any], *, machine: str, tool: str
) -> Any:
    if not result.get("ok", False):
        raise RemoteTransferError(
            f"{tool} on {machine} failed: {result.get('message') or result}"
        )
    data = result.get("data")
    if isinstance(data, dict) and data.get("status") == "error":
        raise RemoteTransferError(
            f"{tool} on {machine} failed: "
            f"{data.get('error_type', 'remote_error')}: "
            f"{data.get('message', '')}"
        )
    return data


async def _remote_transfer_data(
    machine: str,
    tool: str,
    args: dict[str, Any],
    timeout_s: int | None = None,
) -> Any:
    result = await call_remote_worker_tool(machine, tool, args, timeout_s)
    return _unwrap_remote_transfer_result(result, machine=machine, tool=tool)


async def _local_transfer_data(fn: Any, *args: Any) -> dict[str, Any]:
    """Run a local transfer primitive and return JSON-compatible data."""
    data = await asyncio.to_thread(fn, *args)
    jsonable = tool_output_jsonable(data)
    return jsonable if isinstance(jsonable, dict) else {"result": jsonable}


async def copy_local_file_to_remote(
    source_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> RemoteCopyFileOutput:
    """Copy a local controller file to a remote worker using chunked transfer."""
    chunk_bytes = normalize_chunk_size(chunk_size)
    stat = await _local_transfer_data(transfer_stat, source_path, True)
    if stat.get("type") != "file":
        raise ValueError(f"source is not a file: {source_path}")
    begin = await _remote_transfer_data(
        dst_machine,
        "transfer_begin_write",
        {
            "path": dst_path,
            "overwrite": overwrite,
            "expected_bytes": stat["size"],
        },
    )
    transfer_id = begin["transfer_id"]
    chunks = 0
    offset = 0
    try:
        while offset < stat["size"]:
            chunk = await _local_transfer_data(
                transfer_read_chunk, source_path, offset, chunk_bytes
            )
            if chunk["bytes"] == 0:
                break
            await _remote_transfer_data(
                dst_machine,
                "transfer_write_chunk",
                {
                    "path": dst_path,
                    "transfer_id": transfer_id,
                    "offset": offset,
                    "data_b64": chunk["data_b64"],
                    "expected_sha256": chunk["sha256"],
                },
            )
            offset += chunk["bytes"]
            chunks += 1
        finish = await _remote_transfer_data(
            dst_machine,
            "transfer_finish_write",
            {
                "path": dst_path,
                "transfer_id": transfer_id,
                "expected_bytes": stat["size"],
                "expected_sha256": stat.get("sha256"),
            },
        )
    except Exception:
        with suppress(Exception):
            await _remote_transfer_data(
                dst_machine,
                "transfer_abort_write",
                {"path": dst_path, "transfer_id": transfer_id},
            )
        raise
    return RemoteCopyFileOutput.model_validate(
        {
            "source": {"machine": "controller", "path": stat["path"]},
            "destination": {"machine": dst_machine, "path": finish["path"]},
            "bytes": stat["size"],
            "sha256": stat.get("sha256"),
            "chunks": chunks,
            "chunk_size": chunk_bytes,
        }
    )


async def copy_remote_file_to_local(
    src_machine: str,
    src_path: str,
    destination_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> RemoteCopyFileOutput:
    """Copy a remote worker file into the controller workspace."""
    chunk_bytes = normalize_chunk_size(chunk_size)
    stat = await _remote_transfer_data(
        src_machine, "transfer_stat", {"path": src_path, "sha256": True}
    )
    if stat.get("type") != "file":
        raise ValueError(f"source is not a file: {src_path}")
    begin = await _local_transfer_data(
        transfer_begin_write, destination_path, overwrite, stat["size"]
    )
    transfer_id = begin["transfer_id"]
    chunks = 0
    offset = 0
    try:
        while offset < stat["size"]:
            chunk = await _remote_transfer_data(
                src_machine,
                "transfer_read_chunk",
                {"path": src_path, "offset": offset, "chunk_size": chunk_bytes},
            )
            if chunk["bytes"] == 0:
                break
            await asyncio.to_thread(
                transfer_write_chunk,
                destination_path,
                transfer_id,
                offset,
                chunk["data_b64"],
                chunk["sha256"],
            )
            offset += chunk["bytes"]
            chunks += 1
        finish = await _local_transfer_data(
            transfer_finish_write,
            destination_path,
            transfer_id,
            stat["size"],
            stat.get("sha256"),
        )
    except Exception:
        with suppress(Exception):
            await asyncio.to_thread(
                transfer_abort_write, destination_path, transfer_id
            )
        raise
    return RemoteCopyFileOutput.model_validate(
        {
            "source": {"machine": src_machine, "path": stat["path"]},
            "destination": {"machine": "controller", "path": finish["path"]},
            "bytes": stat["size"],
            "sha256": stat.get("sha256"),
            "chunks": chunks,
            "chunk_size": chunk_bytes,
        }
    )


async def copy_remote_file_to_remote(
    src_machine: str,
    src_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> RemoteCopyFileOutput:
    """Copy a file between two remote workers through the control server."""
    chunk_bytes = normalize_chunk_size(chunk_size)
    stat = await _remote_transfer_data(
        src_machine, "transfer_stat", {"path": src_path, "sha256": True}
    )
    if stat.get("type") != "file":
        raise ValueError(f"source is not a file: {src_path}")
    begin = await _remote_transfer_data(
        dst_machine,
        "transfer_begin_write",
        {
            "path": dst_path,
            "overwrite": overwrite,
            "expected_bytes": stat["size"],
        },
    )
    transfer_id = begin["transfer_id"]
    chunks = 0
    offset = 0
    try:
        while offset < stat["size"]:
            chunk = await _remote_transfer_data(
                src_machine,
                "transfer_read_chunk",
                {"path": src_path, "offset": offset, "chunk_size": chunk_bytes},
            )
            if chunk["bytes"] == 0:
                break
            await _remote_transfer_data(
                dst_machine,
                "transfer_write_chunk",
                {
                    "path": dst_path,
                    "transfer_id": transfer_id,
                    "offset": offset,
                    "data_b64": chunk["data_b64"],
                    "expected_sha256": chunk["sha256"],
                },
            )
            offset += chunk["bytes"]
            chunks += 1
        finish = await _remote_transfer_data(
            dst_machine,
            "transfer_finish_write",
            {
                "path": dst_path,
                "transfer_id": transfer_id,
                "expected_bytes": stat["size"],
                "expected_sha256": stat.get("sha256"),
            },
        )
    except Exception:
        with suppress(Exception):
            await _remote_transfer_data(
                dst_machine,
                "transfer_abort_write",
                {"path": dst_path, "transfer_id": transfer_id},
            )
        raise
    return RemoteCopyFileOutput.model_validate(
        {
            "source": {"machine": src_machine, "path": stat["path"]},
            "destination": {"machine": dst_machine, "path": finish["path"]},
            "bytes": stat["size"],
            "sha256": stat.get("sha256"),
            "chunks": chunks,
            "chunk_size": chunk_bytes,
        }
    )


async def _remote_cleanup_file(machine: str, path: str) -> None:
    with suppress(Exception):
        await _remote_transfer_data(
            machine,
            "delete_file_or_dir",
            {"path": path, "recursive": False},
        )


async def copy_remote_dir_to_remote(
    src_machine: str,
    src_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> RemoteCopyDirOutput:
    """Copy a directory tree between remote workers using temporary archives."""
    pack = await _remote_transfer_data(
        src_machine,
        "transfer_pack_dir",
        {"path": src_path, "compression": "gz"},
    )
    dst_archive = await _remote_transfer_data(
        dst_machine, "transfer_alloc_temp_path", {"suffix": ".tar.gz"}
    )
    try:
        copy_result = await copy_remote_file_to_remote(
            src_machine,
            pack["archive_path"],
            dst_machine,
            dst_archive["path"],
            True,
            chunk_size,
        )
        unpack = await _remote_transfer_data(
            dst_machine,
            "transfer_unpack_archive",
            {
                "archive_path": dst_archive["path"],
                "dst_path": dst_path,
                "overwrite": overwrite,
                "cleanup_archive": True,
            },
        )
    except Exception:
        await _remote_cleanup_file(dst_machine, dst_archive.get("path", ""))
        raise
    finally:
        await _remote_cleanup_file(src_machine, pack.get("archive_path", ""))
    return RemoteCopyDirOutput.model_validate(
        {
            "source": {"machine": src_machine, "path": pack["path"]},
            "destination": {"machine": dst_machine, "path": unpack["path"]},
            "archive_bytes": pack["bytes"],
            "archive_sha256": pack["sha256"],
            "chunks": copy_result.chunks,
            "entries": unpack["entries"],
        }
    )


async def copy_remote_dir_to_local(
    src_machine: str,
    src_path: str,
    destination_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> RemoteCopyDirOutput:
    """Copy a remote worker directory into the controller workspace."""
    pack = await _remote_transfer_data(
        src_machine,
        "transfer_pack_dir",
        {"path": src_path, "compression": "gz"},
    )
    archive = await _local_transfer_data(transfer_alloc_temp_path, ".tar.gz")
    try:
        copy_result = await copy_remote_file_to_local(
            src_machine, pack["archive_path"], archive["path"], True, chunk_size
        )
        unpack = await _local_transfer_data(
            transfer_unpack_archive,
            archive["path"],
            destination_path,
            overwrite,
            True,
        )
    finally:
        await _remote_cleanup_file(src_machine, pack.get("archive_path", ""))
    return RemoteCopyDirOutput.model_validate(
        {
            "source": {"machine": src_machine, "path": pack["path"]},
            "destination": {"machine": "controller", "path": unpack["path"]},
            "archive_bytes": pack["bytes"],
            "archive_sha256": pack["sha256"],
            "chunks": copy_result.chunks,
            "entries": unpack["entries"],
        }
    )


async def copy_local_dir_to_remote(
    source_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> RemoteCopyDirOutput:
    """Copy a controller directory tree to a remote worker."""
    pack = await _local_transfer_data(transfer_pack_dir, source_path, "gz")
    dst_archive = await _remote_transfer_data(
        dst_machine, "transfer_alloc_temp_path", {"suffix": ".tar.gz"}
    )
    try:
        copy_result = await copy_local_file_to_remote(
            pack["archive_path"],
            dst_machine,
            dst_archive["path"],
            True,
            chunk_size,
        )
        unpack = await _remote_transfer_data(
            dst_machine,
            "transfer_unpack_archive",
            {
                "archive_path": dst_archive["path"],
                "dst_path": dst_path,
                "overwrite": overwrite,
                "cleanup_archive": True,
            },
        )
    except Exception:
        await _remote_cleanup_file(dst_machine, dst_archive.get("path", ""))
        raise
    finally:
        with suppress(Exception):
            delete_file_or_dir_execute(pack.get("archive_path", ""), False)
    return RemoteCopyDirOutput.model_validate(
        {
            "source": {"machine": "controller", "path": pack["path"]},
            "destination": {"machine": dst_machine, "path": unpack["path"]},
            "archive_bytes": pack["bytes"],
            "archive_sha256": pack["sha256"],
            "chunks": copy_result.chunks,
            "entries": unpack["entries"],
        }
    )
