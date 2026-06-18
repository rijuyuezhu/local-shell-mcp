"""Typed input annotations for file operation tools."""

from typing import Annotated, Any

from pydantic import Field

FilePathArg = Annotated[
    str,
    Field(
        description="Workspace-relative path, or an allowed absolute path, for the file or directory operation."
    ),
]
ListPathArg = Annotated[
    str,
    Field(
        description="Directory path to list. Relative paths resolve inside the configured workspace."
    ),
]
RecursiveArg = Annotated[
    bool,
    Field(
        description="Whether to recurse into descendant directories. Required for deleting non-empty directories."
    ),
]
MaxEntriesArg = Annotated[
    int,
    Field(
        description="Maximum number of entries to return before reporting truncation. Bounded by the server configuration."
    ),
]
StartLineArg = Annotated[
    int | None,
    Field(
        description="Optional 1-based first line to include when reading text files. Omit to start at the first line."
    ),
]
EndLineArg = Annotated[
    int | None,
    Field(
        description="Optional 1-based final line to include when reading text files. Omit to read through the end."
    ),
]
BinaryPreviewArg = Annotated[
    str | None,
    Field(
        description="Optional binary preview encoding for binary files. Supported values are 'hex' and 'base64'."
    ),
]
BinaryPreviewBytesArg = Annotated[
    int,
    Field(
        description="Maximum number of binary bytes to include in the optional preview, bounded by the server configuration."
    ),
]
PathsArg = Annotated[
    list[str],
    Field(
        description="Target file paths to read. Keep the list focused; server limits bound count and total returned bytes."
    ),
]
FileContentArg = Annotated[
    str,
    Field(
        description="Complete UTF-8 text content to write to the target file."
    ),
]
OverwriteArg = Annotated[
    bool,
    Field(
        description="Whether to replace an existing file. Set false to fail when the target already exists."
    ),
]
OldTextArg = Annotated[
    str,
    Field(
        description="Exact existing text to replace. Include enough surrounding context to make the match unique unless replace_all is true."
    ),
]
NewTextArg = Annotated[
    str,
    Field(
        description="Replacement text written in place of the matched old text."
    ),
]
ReplaceAllArg = Annotated[
    bool,
    Field(
        description="Whether to replace every exact occurrence. Leave false when only one precise occurrence should change."
    ),
]
EditsArg = Annotated[
    list[dict[str, Any]],
    Field(
        description="Ordered exact-text edits. Each edit must include old and new strings, with optional replace_all."
    ),
]
