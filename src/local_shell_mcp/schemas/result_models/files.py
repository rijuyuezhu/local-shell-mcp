"""Typed structured outputs for file operation tools."""

from pydantic import BaseModel, Field


class EntryInfo(BaseModel):
    """One file-system entry in a directory listing."""

    path: str = Field(description="Workspace-relative entry path.")
    type: str = Field(description="Entry type: file, dir, or other.")
    size: int | None = Field(
        default=None,
        description="File size in bytes, or null for directories and other entries.",
    )
    modified: float = Field(
        description="Last modification time as a Unix timestamp."
    )


class ListFilesOutput(BaseModel):
    """Directory listing result."""

    limit_count: int = Field(
        description="Maximum number of entries limited by the request or configuration."
    )
    count: int = Field(description="Number of entries returned in entries.")
    is_truncated: bool = Field(
        description="Whether more entries existed beyond the configured or requested limit."
    )
    entries: list[EntryInfo] = Field(description="Returned directory entries.")


class ReadFileOutput(BaseModel):
    """Text file content or safe binary-file metadata."""

    path: str = Field(description="Workspace-relative file path that was read.")
    bytes: int = Field(description="Total file size in bytes.")
    bytes_read: int | None = Field(
        default=None,
        description="Number of bytes read into the text response, when applicable.",
    )
    truncated_bytes: int | None = Field(
        default=None,
        description="Number of file bytes omitted due to the read limit, when applicable.",
    )
    binary: bool = Field(
        description="Whether the file was classified as binary."
    )
    total_lines: int | None = Field(
        default=None,
        description="Total decoded text line count before optional line-range selection.",
    )
    truncated: bool = Field(
        default=False,
        description="Whether text content was truncated to fit the read limit.",
    )
    content: str | None = Field(
        default=None,
        description="Decoded UTF-8 text content, or null for binary files.",
    )
    message: str | None = Field(
        default=None,
        description="Human-readable note for binary or otherwise special read results.",
    )
    preview: str | None = Field(
        default=None,
        description="Optional bounded binary preview encoded as requested.",
    )
    preview_encoding: str | None = Field(
        default=None,
        description="Encoding used for preview, such as hex or base64.",
    )
    preview_bytes: int | None = Field(
        default=None,
        description="Number of raw binary bytes included in preview.",
    )


class ReadManyFilesOutput(BaseModel):
    """Batch file read result."""

    files: list[ReadFileOutput] = Field(
        description="Per-file read results in request order."
    )
    total_content_bytes: int = Field(
        description="Total UTF-8 bytes returned across text content and binary previews."
    )


class WriteFileOutput(BaseModel):
    """File write result."""

    path: str = Field(
        description="Workspace-relative file path that was written."
    )
    bytes: int = Field(description="Number of UTF-8 bytes written.")
    created: bool = Field(
        description="Whether the file did not exist before this write."
    )


class EditFileOutput(BaseModel):
    """Exact-text edit result."""

    path: str = Field(
        description="Workspace-relative file path that was edited."
    )
    replacements: int = Field(
        description="Number of exact-text replacements applied."
    )


class MultiEditFileOutput(EditFileOutput):
    """Multiple exact-text edit result."""


class DeleteFileOrDirOutput(BaseModel):
    """File or directory deletion result."""

    path: str = Field(description="Workspace-relative path that was deleted.")
    deleted: str = Field(
        description="Deleted item type, usually file or directory."
    )
