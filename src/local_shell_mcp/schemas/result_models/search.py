"""Typed structured outputs for search and tree-view tools."""

from pydantic import BaseModel, Field

from .files import LineRange


class TreeViewOutput(BaseModel):
    """Compact directory tree result."""

    root: str = Field(description="Resolved root path used for the tree view.")
    exists: bool = Field(description="Whether the requested tree root exists.")
    is_directory: bool = Field(
        description="Whether the requested root is a directory."
    )
    entries: list[str] = Field(
        description="Indented tree entries relative to root."
    )
    count: int = Field(description="Number of entries returned.")
    truncated: bool = Field(
        description="Whether additional entries were omitted due to limits."
    )
    message: str | None = Field(
        default=None,
        description="Optional diagnostic message for missing or non-directory roots.",
    )
    nearest_existing_parent: str | None = Field(
        default=None,
        description="Nearest existing parent for a missing root, when available.",
    )
    nearest_parent_entries: list[str] | None = Field(
        default=None,
        description="Entries in the nearest existing parent for a missing root.",
    )
    nearest_parent_entries_truncated: bool | None = Field(
        default=None,
        description="Whether nearest_parent_entries was truncated.",
    )


class GlobSearchOutput(BaseModel):
    """Glob file search result."""

    paths: list[str] = Field(
        description="Workspace-relative paths matching the glob pattern."
    )


class GrepMatch(BaseModel):
    """One ripgrep match."""

    path: str | None = Field(
        description="Path containing the match, when reported by ripgrep."
    )
    line: int | None = Field(
        description="1-based line number containing the match."
    )
    column: int | None = Field(
        description="1-based column number for the first match on the line."
    )
    text: str = Field(
        description="Matching line text without the trailing newline."
    )
    numbered_line: str | None = Field(
        default=None,
        description="Grounded match text with optional hashline header plus 'line:text' row.",
    )
    session_id: str | None = Field(
        default=None,
        description="Agent grounding session that recorded this match line.",
    )
    snapshot_id: str | None = Field(
        default=None,
        description="Snapshot handle for the displayed match line, usable with edit_lines.",
    )
    file_sha256: str | None = Field(
        default=None,
        description="SHA-256 digest of the complete matched file when displayed.",
    )
    seen_range: LineRange | None = Field(
        default=None,
        description="Inclusive original line range shown for this match.",
    )


class GrepSearchOutput(BaseModel):
    """Ripgrep content search result."""

    ok: bool = Field(
        description="Whether ripgrep completed successfully or with no matches."
    )
    matches: list[GrepMatch] = Field(description="Returned ripgrep matches.")
    count: int = Field(description="Number of matches returned.")
    truncated: bool = Field(
        description="Whether results were truncated by match or output limits."
    )
    stderr: str = Field(
        description="Captured ripgrep stderr, after output limiting."
    )
    numbered_content: str = Field(
        default="",
        description="Grouped grounded match snippets with line-numbered rows.",
    )
