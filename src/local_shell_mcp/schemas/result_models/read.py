"""Typed structured outputs for the read tool."""

from typing import Literal

from pydantic import BaseModel, Field

from .files import ListFilesOutput, ReadFileOutput


class ReadOutput(BaseModel):
    """Read result for files and directories."""

    kind: Literal["file", "directory"] = Field(
        description="Type of target that was read."
    )
    path: str = Field(description="Workspace-relative target path.")
    raw: bool = Field(
        default=False,
        description="Whether content omits model-facing line-number prefixes.",
    )
    content: str = Field(
        description="Model-facing content. File reads use numbered_content unless raw is true; directories use a compact listing."
    )
    file: ReadFileOutput | None = Field(
        default=None,
        description="Structured file read data when kind is file.",
    )
    directory: ListFilesOutput | None = Field(
        default=None,
        description="Structured directory listing data when kind is directory.",
    )
