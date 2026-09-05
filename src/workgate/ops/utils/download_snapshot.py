"""Private immutable snapshots used by tokenized file links."""

import base64
import binascii
import contextlib
import hashlib
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from ...config.settings import get_settings
from ...persistence import get_state_store
from ...schemas.result_models.transfer import (
    TransferReadChunkOutput,
    TransferStatOutput,
)
from ...tool_session.store import AgentSession, resolve_session_path
from ..transfer import DEFAULT_TRANSFER_CHUNK_BYTES
from .path import relative_display, resolve_path
from .remote_session import call_remote_session_tool

SNAPSHOT_SUFFIX = ".bin"
STAGING_SUFFIX = ".tmp"


@dataclass(frozen=True)
class DownloadSnapshot:
    """One creation-time file snapshot awaiting durable registration."""

    staging_path: Path
    """Private temporary file containing the completed snapshot bytes."""

    display_path: str
    """Session-relative source path displayed to the caller."""

    source_name: str
    """Original source basename used for MIME inference."""

    size: int
    """Snapshot size in bytes."""

    sha256: str
    """SHA-256 digest of the complete snapshot bytes."""

    target: str
    """Source session target: local or remote."""

    machine: str | None = None
    """Remote worker machine name when target is remote."""


def snapshot_directory() -> Path:
    """Return the private directory containing file-link snapshots."""
    path = get_state_store().layout.download_snapshots_dir
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.chmod(0o700)
    return path


def new_staging_path() -> Path:
    """Allocate a private staging path in the snapshot directory."""
    return snapshot_directory() / f".{uuid.uuid4().hex}{STAGING_SUFFIX}"


def new_snapshot_path() -> Path:
    """Allocate an opaque final snapshot path."""
    return snapshot_directory() / f"{uuid.uuid4().hex}{SNAPSHOT_SUFFIX}"


def open_private_staging(path: Path) -> BinaryIO:
    """Create and open one exclusive private staging file."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, "wb")


def assert_shareable_size(size: int) -> None:
    """Reject invalid or over-limit snapshot sizes."""
    maximum = get_settings().file_download_max_file_bytes
    if size < 0:
        raise ValueError("File size is invalid")
    if maximum > 0 and size > maximum:
        raise ValueError(f"File is too large: {size}")


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
    )


def create_local_snapshot(
    path: str, session: AgentSession | None
) -> DownloadSnapshot:
    """Copy one local regular file into a creation-time snapshot."""
    resolved = (
        resolve_session_path(session, path, must_exist=True)
        if session is not None
        else resolve_path(path, must_exist=True)
    )
    staging = new_staging_path()
    source: BinaryIO | None = None
    try:
        flags = os.O_RDONLY
        flags |= int(getattr(os, "O_BINARY", 0))
        flags |= int(getattr(os, "O_NOFOLLOW", 0))
        source = os.fdopen(os.open(resolved, flags), "rb")
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"Not a regular file: {path}")
        assert_shareable_size(int(before.st_size))

        digest = hashlib.sha256()
        copied = 0
        with open_private_staging(staging) as destination:
            while chunk := source.read(DEFAULT_TRANSFER_CHUNK_BYTES):
                copied += len(chunk)
                assert_shareable_size(copied)
                destination.write(chunk)
                digest.update(chunk)
            destination.flush()
        after = os.fstat(source.fileno())
        if _identity(before) != _identity(after) or copied != int(
            before.st_size
        ):
            raise RuntimeError(
                "Source file changed while creating the snapshot"
            )
        return DownloadSnapshot(
            staging_path=staging,
            display_path=relative_display(resolved),
            source_name=resolved.name,
            size=copied,
            sha256=digest.hexdigest(),
            target="local",
        )
    except Exception:
        staging.unlink(missing_ok=True)
        raise
    finally:
        if source is not None:
            source.close()


def _decode_remote_chunk(
    payload: TransferReadChunkOutput,
    *,
    expected_offset: int,
    expected_size: int,
) -> bytes:
    if payload.offset != expected_offset:
        raise RuntimeError(
            "Remote snapshot chunk offset mismatch: "
            f"expected {expected_offset}, got {payload.offset}"
        )
    if payload.size != expected_size:
        raise RuntimeError(
            "Remote snapshot size changed: "
            f"expected {expected_size}, got {payload.size}"
        )
    try:
        data = base64.b64decode(payload.data_b64.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise RuntimeError("Remote snapshot chunk is not valid base64") from exc
    if len(data) != payload.bytes:
        raise RuntimeError(
            "Remote snapshot chunk length mismatch: "
            f"expected {payload.bytes}, got {len(data)}"
        )
    if hashlib.sha256(data).hexdigest() != payload.sha256:
        raise RuntimeError("Remote snapshot chunk SHA-256 mismatch")
    return data


async def create_remote_snapshot(
    path: str, session: AgentSession
) -> DownloadSnapshot:
    """Stream one remote regular file into a private local snapshot."""
    stat_payload = TransferStatOutput.model_validate(
        await call_remote_session_tool(
            session,
            "transfer_stat",
            {"path": path, "sha256": True},
        )
    )
    if stat_payload.type != "file" or stat_payload.size is None:
        raise ValueError(f"Not a regular file: {path}")
    expected_size = int(stat_payload.size)
    assert_shareable_size(expected_size)

    staging = new_staging_path()
    digest = hashlib.sha256()
    offset = 0
    try:
        with open_private_staging(staging) as destination:
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
                        "Remote snapshot transfer ended before completion"
                    )
                destination.write(decoded)
                digest.update(decoded)
                offset += len(decoded)
                if chunk.eof and offset != expected_size:
                    raise RuntimeError(
                        "Remote snapshot reported EOF before completion"
                    )
                if not chunk.eof and offset >= expected_size:
                    raise RuntimeError(
                        "Remote snapshot omitted EOF at the expected size"
                    )
            destination.flush()
        actual_digest = digest.hexdigest()
        if offset != expected_size:
            raise RuntimeError("Remote snapshot transfer size mismatch")
        if stat_payload.sha256 and actual_digest != stat_payload.sha256:
            raise RuntimeError(
                "Remote file changed while creating the snapshot"
            )
        source_name = Path(stat_payload.path or path).name or Path(path).name
        return DownloadSnapshot(
            staging_path=staging,
            display_path=stat_payload.path,
            source_name=source_name,
            size=expected_size,
            sha256=actual_digest,
            target="remote",
            machine=session.machine,
        )
    except BaseException:
        staging.unlink(missing_ok=True)
        raise
