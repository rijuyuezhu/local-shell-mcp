"""Session-bound native image loading for local and remote workspaces."""

import asyncio
import base64
import binascii
import hashlib
from dataclasses import dataclass

from mcp.types import CallToolResult, ImageContent, TextContent

from ..config.settings import get_settings
from ..schemas.result_models.image import ViewImageOutput
from ..schemas.result_models.transfer import (
    TransferReadChunkOutput,
    TransferStatOutput,
)
from ..tool_session.store import (
    AgentSession,
    get_tool_session_store,
    resolve_session_path,
)
from .transfer import DEFAULT_TRANSFER_CHUNK_BYTES
from .utils.path import relative_display
from .utils.remote_session import call_remote_session_tool


@dataclass(frozen=True)
class _ImageFile:
    path: str
    data: bytes
    format: str
    mime_type: str
    size: int


def detect_image_type(header: bytes) -> tuple[str, str]:
    """Detect one supported image type from bounded file magic."""
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg", "image/jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif", "image/gif"
    if (
        len(header) >= 12
        and header.startswith(b"RIFF")
        and header[8:12] == b"WEBP"
    ):
        return "webp", "image/webp"
    raise ValueError(
        "Unsupported image format; expected PNG, JPEG, GIF, or WebP"
    )


def _assert_image_size(size: int) -> None:
    """Reject empty or oversized native-image payloads."""
    maximum = max(1, int(get_settings().max_view_image_bytes))
    if size <= 0:
        raise ValueError("Image file is empty")
    if size > maximum:
        raise ValueError(f"Refusing image of {size} bytes; max is {maximum}")


def _local_image(path: str, session: AgentSession) -> _ImageFile:
    """Read one bounded image from a local session workdir."""
    resolved = resolve_session_path(session, path, must_exist=True)
    if not resolved.is_file():
        raise IsADirectoryError(str(resolved))
    expected_size = resolved.stat().st_size
    _assert_image_size(expected_size)
    with resolved.open("rb") as handle:
        data = handle.read(expected_size + 1)
    if len(data) != expected_size:
        raise RuntimeError("Image changed while it was being read")
    _assert_image_size(len(data))
    image_format, mime_type = detect_image_type(data[:16])
    return _ImageFile(
        path=relative_display(resolved),
        data=data,
        format=image_format,
        mime_type=mime_type,
        size=len(data),
    )


def _decode_remote_chunk(
    payload: TransferReadChunkOutput,
    *,
    expected_offset: int,
    expected_size: int,
) -> bytes:
    """Validate and decode one remote transfer chunk."""
    if payload.offset != expected_offset:
        raise RuntimeError(
            f"Remote image chunk offset mismatch: expected {expected_offset}, "
            f"got {payload.offset}"
        )
    if payload.size != expected_size:
        raise RuntimeError(
            f"Remote image size changed: expected {expected_size}, got {payload.size}"
        )
    try:
        data = base64.b64decode(payload.data_b64.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise RuntimeError("Remote image chunk is not valid base64") from exc
    if len(data) != payload.bytes:
        raise RuntimeError(
            f"Remote image chunk length mismatch: expected {payload.bytes}, "
            f"got {len(data)}"
        )
    digest = hashlib.sha256(data).hexdigest()
    if digest != payload.sha256:
        raise RuntimeError("Remote image chunk SHA-256 mismatch")
    return data


async def _remote_image(path: str, session: AgentSession) -> _ImageFile:
    """Read one bounded image through the existing remote transfer protocol."""
    stat = TransferStatOutput.model_validate(
        await call_remote_session_tool(
            session,
            "transfer_stat",
            {"path": path, "sha256": False},
        )
    )
    if stat.type != "file" or stat.size is None:
        raise ValueError(f"Image path is not a file: {path}")
    expected_size = int(stat.size)
    _assert_image_size(expected_size)

    data = bytearray()
    offset = 0
    while offset < expected_size:
        chunk = TransferReadChunkOutput.model_validate(
            await call_remote_session_tool(
                session,
                "transfer_read_chunk",
                {
                    "path": path,
                    "offset": offset,
                    "chunk_size": min(
                        DEFAULT_TRANSFER_CHUNK_BYTES,
                        expected_size - offset,
                    ),
                },
            )
        )
        decoded = _decode_remote_chunk(
            chunk,
            expected_offset=offset,
            expected_size=expected_size,
        )
        if not decoded:
            raise RuntimeError(
                "Remote image transfer ended before the file was complete"
            )
        data.extend(decoded)
        offset += len(decoded)
        if chunk.eof and offset != expected_size:
            raise RuntimeError(
                "Remote image transfer reported EOF before the file was complete"
            )
        if not chunk.eof and offset >= expected_size:
            raise RuntimeError(
                "Remote image transfer omitted EOF at the expected file size"
            )

    raw = bytes(data)
    _assert_image_size(len(raw))
    image_format, mime_type = detect_image_type(raw[:16])
    return _ImageFile(
        path=stat.path,
        data=raw,
        format=image_format,
        mime_type=mime_type,
        size=len(raw),
    )


async def read_image_dispatch_execute(path: str, session_id: str) -> _ImageFile:
    """Load one local or remote image through an explicit agent session."""
    session = get_tool_session_store().touch_session(session_id)
    if session.target == "remote":
        return await _remote_image(path, session)
    return await asyncio.to_thread(_local_image, path, session)


async def view_image_dispatch_execute(
    path: str, session_id: str
) -> CallToolResult:
    """Return native MCP image content plus structured session metadata."""
    session = get_tool_session_store().touch_session(session_id)
    image = await read_image_dispatch_execute(path, session_id)
    metadata = ViewImageOutput(
        session_id=session.session_id,
        target=session.target,
        machine=session.machine,
        path=image.path,
        mime_type=image.mime_type,
        bytes=image.size,
    )
    return CallToolResult(
        content=[
            ImageContent(
                type="image",
                data=base64.b64encode(image.data).decode("ascii"),
                mimeType=image.mime_type,
            ),
            TextContent(
                type="text",
                text=f"{image.path} ({image.mime_type}, {image.size} bytes)",
            ),
        ],
        structuredContent=metadata.model_dump(mode="json"),
    )
