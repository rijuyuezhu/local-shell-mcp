"""Internal transfer operation tool registry for remote-worker file moves."""

import asyncio
from typing import Any

from ...ops.transfer_ops import (
    transfer_abort_write as transfer_abort_write_sync,
)
from ...ops.transfer_ops import (
    transfer_alloc_temp_path as transfer_alloc_temp_path_sync,
)
from ...ops.transfer_ops import (
    transfer_begin_write as transfer_begin_write_sync,
)
from ...ops.transfer_ops import (
    transfer_finish_write as transfer_finish_write_sync,
)
from ...ops.transfer_ops import (
    transfer_pack_dir as transfer_pack_dir_sync,
)
from ...ops.transfer_ops import (
    transfer_read_chunk as transfer_read_chunk_sync,
)
from ...ops.transfer_ops import (
    transfer_stat as transfer_stat_sync,
)
from ...ops.transfer_ops import (
    transfer_unpack_archive as transfer_unpack_archive_sync,
)
from ...ops.transfer_ops import (
    transfer_write_chunk as transfer_write_chunk_sync,
)
from ...schemas.result_models.transfer import (
    TransferAbortWriteOutput,
    TransferAllocTempPathOutput,
    TransferBeginWriteOutput,
    TransferFinishWriteOutput,
    TransferPackDirOutput,
    TransferReadChunkOutput,
    TransferStatOutput,
    TransferUnpackArchiveOutput,
    TransferWriteChunkOutput,
)
from ..contracts import HttpToolRoute
from ..declarative import DeclarativeToolRegistry


class TransferToolRegistry(DeclarativeToolRegistry):
    """Register worker-side transfer primitives without public routes."""

    name = "transfer"

    def http_routes(self) -> tuple[HttpToolRoute, ...]:
        """Keep raw transfer primitives off the public REST surface."""
        return ()

    def register_mcp(self, *args: Any, **kwargs: Any) -> None:
        """Keep raw transfer primitives off the public MCP surface."""
        return None


local_tool = TransferToolRegistry.get_tool_decorator()


@local_tool(http_method="POST", http_path="/tools/transfer_stat")
async def transfer_stat(path: str, sha256: bool = True) -> TransferStatOutput:
    """Return transfer metadata for a file or directory."""
    return await asyncio.to_thread(transfer_stat_sync, path, sha256)


@local_tool(http_method="POST", http_path="/tools/transfer_read_chunk")
async def transfer_read_chunk(
    path: str, offset: int = 0, chunk_size: int | None = None
) -> TransferReadChunkOutput:
    """Read one base64-encoded binary chunk from a file."""
    return await asyncio.to_thread(
        transfer_read_chunk_sync, path, offset, chunk_size
    )


@local_tool(http_method="POST", http_path="/tools/transfer_begin_write")
async def transfer_begin_write(
    path: str, overwrite: bool = True, expected_bytes: int | None = None
) -> TransferBeginWriteOutput:
    """Start an atomic chunked file write and return a transfer id."""
    return await asyncio.to_thread(
        transfer_begin_write_sync, path, overwrite, expected_bytes
    )


@local_tool(http_method="POST", http_path="/tools/transfer_write_chunk")
async def transfer_write_chunk(
    path: str,
    transfer_id: str,
    offset: int,
    data_b64: str,
    expected_sha256: str | None = None,
) -> TransferWriteChunkOutput:
    """Write one base64-encoded chunk into an active transfer."""
    return await asyncio.to_thread(
        transfer_write_chunk_sync,
        path,
        transfer_id,
        offset,
        data_b64,
        expected_sha256,
    )


@local_tool(http_method="POST", http_path="/tools/transfer_finish_write")
async def transfer_finish_write(
    path: str,
    transfer_id: str,
    expected_bytes: int | None = None,
    expected_sha256: str | None = None,
) -> TransferFinishWriteOutput:
    """Validate and atomically finish an active transfer."""
    return await asyncio.to_thread(
        transfer_finish_write_sync,
        path,
        transfer_id,
        expected_bytes,
        expected_sha256,
    )


@local_tool(http_method="POST", http_path="/tools/transfer_abort_write")
async def transfer_abort_write(
    path: str, transfer_id: str
) -> TransferAbortWriteOutput:
    """Abort an active transfer and remove its temporary file."""
    return await asyncio.to_thread(transfer_abort_write_sync, path, transfer_id)


@local_tool(http_method="POST", http_path="/tools/transfer_alloc_temp_path")
async def transfer_alloc_temp_path(
    suffix: str = ".bin",
) -> TransferAllocTempPathOutput:
    """Allocate a safe temporary path for transfer archives."""
    return await asyncio.to_thread(transfer_alloc_temp_path_sync, suffix)


@local_tool(http_method="POST", http_path="/tools/transfer_pack_dir")
async def transfer_pack_dir(
    path: str, compression: str = "gz"
) -> TransferPackDirOutput:
    """Pack a directory into a temporary tar archive."""
    return await asyncio.to_thread(transfer_pack_dir_sync, path, compression)


@local_tool(http_method="POST", http_path="/tools/transfer_unpack_archive")
async def transfer_unpack_archive(
    archive_path: str,
    dst_path: str,
    overwrite: bool = True,
    cleanup_archive: bool = True,
) -> TransferUnpackArchiveOutput:
    """Safely unpack a transfer archive into a destination directory."""
    return await asyncio.to_thread(
        transfer_unpack_archive_sync,
        archive_path,
        dst_path,
        overwrite,
        cleanup_archive,
    )
