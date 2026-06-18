"""Typed structured outputs for transfer tools."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TransferStatOutput(BaseModel):
    """File, directory, or other path metadata for transfer planning."""

    path: str = Field(description="Workspace-relative path that was inspected.")
    type: str = Field(description="Path type: file, dir, or other.")
    size: int | None = Field(
        description="Size in bytes for files and other path types, or null for directories."
    )
    modified: float = Field(
        description="Last modification time as a Unix timestamp."
    )
    sha256: str | None = Field(
        default=None, description="Optional SHA-256 digest for file contents."
    )


class TransferReadChunkOutput(BaseModel):
    """Base64-encoded chunk read from a file."""

    path: str
    offset: int
    bytes: int
    size: int
    eof: bool
    sha256: str
    data_b64: str


class TransferBeginWriteOutput(BaseModel):
    """State for a newly started chunked file write."""

    path: str
    temp_path: str
    transfer_id: str
    created: bool
    expected_bytes: int | None = None


class TransferWriteChunkOutput(BaseModel):
    """Result of writing one chunk to a temporary transfer file."""

    path: str
    temp_path: str
    offset: int
    bytes: int
    sha256: str


class TransferFinishWriteOutput(BaseModel):
    """Result of atomically completing a chunked file write."""

    path: str
    bytes: int
    sha256: str | None = None
    completed: bool


class TransferAbortWriteOutput(BaseModel):
    """Result of removing an in-progress temporary transfer file."""

    path: str
    temp_path: str
    deleted: bool


class TransferAllocTempPathOutput(BaseModel):
    """Allocated workspace-relative temporary transfer path."""

    path: str


class TransferPackDirOutput(BaseModel):
    """Archive created from a directory for transfer."""

    path: str
    archive_path: str
    bytes: int
    sha256: str
    compression: str


class TransferUnpackArchiveOutput(BaseModel):
    """Archive unpack result."""

    path: str
    archive_path: str
    entries: int
    completed: bool
    archive_deleted: bool


class TransferGenericOutput(BaseModel):
    """Fallback transfer output for dynamically shaped transfer helpers."""

    model_config = ConfigDict(extra="allow")

    root: dict[str, Any] | None = None
