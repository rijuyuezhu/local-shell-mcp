"""Typed input annotations for file operation tools."""

from typing import Annotated

from pydantic import BaseModel, Field

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
ToolSessionIdArg = Annotated[
    str | None,
    Field(
        description="Optional explicit agent/workspace session id returned by session_start. Internal helpers may omit it when no grounding snapshot is needed."
    ),
]
EditStartLineArg = Annotated[
    int,
    Field(
        description="1-based first original line to replace. The range is inclusive."
    ),
]
EditEndLineArg = Annotated[
    int,
    Field(
        description="1-based final original line to replace. The range is inclusive."
    ),
]
LineReplacementArg = Annotated[
    str,
    Field(
        description="Replacement text for the selected whole-line range. Use an empty string to delete the range."
    ),
]
SnapshotIdArg = Annotated[
    str | None,
    Field(
        description="Optional snapshot_id returned by read or search. When provided, the edit is rejected if the file changed or the line range was not shown."
    ),
]


class ReadFileRequest(BaseModel):
    """One UTF-8 file read request with an optional per-file line range."""

    path: FilePathArg
    """Workspace-relative or allowed absolute path to read."""

    start_line: StartLineArg = None
    """Optional 1-based first line to include for this file."""

    end_line: EndLineArg = None
    """Optional 1-based final line to include for this file."""


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
