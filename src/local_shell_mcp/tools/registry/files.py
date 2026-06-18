"""File operation tool registry."""

import asyncio

from pydantic import TypeAdapter

from ...ops.files import (
    delete_file_or_dir_execute,
    edit_file_execute,
    list_files_execute,
    multi_edit_file_execute,
    read_file_execute,
    read_many_files_execute,
    write_file_execute,
)
from ...schemas.input_models.files import (
    EditsArg,
    EndLineArg,
    FileContentArg,
    FilePathArg,
    ListPathArg,
    MaxEntriesArg,
    NewTextArg,
    OldTextArg,
    OverwriteArg,
    ReadFilesArg,
    RecursiveArg,
    ReplaceAllArg,
    StartLineArg,
)
from ...schemas.result_models.files import (
    DeleteFileOrDirOutput,
    EditFileOutput,
    ListFilesOutput,
    MultiEditFileOutput,
    ReadFileOutput,
    ReadManyFilesOutput,
    WriteFileOutput,
)
from ..contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry


class FileToolRegistry(DeclarativeToolRegistry):
    """Register file operation tools."""

    name = "file"
    """Registry group name used for tool-surface organization."""


local_tool = FileToolRegistry.get_tool_decorator()


def _list_files_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""List files and directories under a path for quick inspection. The result reports whether entries were truncated by the requested limit or server cap. Current max directory entries: {settings.max_directory_entries}."""


def _read_file_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Read a UTF-8 text file, optionally by line range. Use after locating a file to inspect exact content before editing. Current per-file read cap: {settings.max_file_read_bytes} bytes."""


def _read_many_files_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Read multiple UTF-8 text files with optional per-file line ranges. Use for targeted context gathering across known paths. Current limits: {settings.max_read_many_files} files and {settings.max_read_many_total_bytes} returned bytes."""


def _write_file_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Write a full UTF-8 text file. Use to create a new file or intentionally replace a whole file. Current write cap: {settings.max_file_write_bytes} bytes. For precise modifications, prefer edit_file or apply_patch."""


def _edit_file_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Replace exact text in a validated UTF-8 text file. Use for small precise edits after reading the target file. Current write cap: {settings.max_file_write_bytes} bytes. For larger or multi-file changes, prefer apply_patch."""


@local_tool(
    http_method="POST",
    http_path="/tools/list_files",
    description=_list_files_description,
)
async def list_files(
    path: ListPathArg = ".",
    recursive: RecursiveArg = False,
    max_entries: MaxEntriesArg = 500,
) -> ListFilesOutput:
    """List files and directories under a path."""
    return await asyncio.to_thread(
        list_files_execute, path, recursive, max_entries
    )


@local_tool(
    http_method="POST",
    http_path="/tools/read_file",
    description=_read_file_description,
)
async def read_file(
    path: FilePathArg,
    start_line: StartLineArg = None,
    end_line: EndLineArg = None,
) -> ReadFileOutput:
    """Read a UTF-8 text file, optionally by line range."""
    return await asyncio.to_thread(
        read_file_execute,
        path,
        start_line,
        end_line,
    )


@local_tool(
    http_method="POST",
    http_path="/tools/read_many_files",
    description=_read_many_files_description,
)
async def read_many_files(files: ReadFilesArg) -> ReadManyFilesOutput:
    """Read multiple UTF-8 text files with optional per-file line ranges."""
    return await asyncio.to_thread(
        read_many_files_execute,
        TypeAdapter(ReadFilesArg).validate_python(files),
    )


@local_tool(
    http_method="POST",
    http_path="/tools/write_file",
    description=_write_file_description,
)
async def write_file(
    path: FilePathArg, content: FileContentArg, overwrite: OverwriteArg = True
) -> WriteFileOutput:
    """Write a UTF-8 text file."""
    return await asyncio.to_thread(write_file_execute, path, content, overwrite)


@local_tool(
    http_method="POST",
    http_path="/tools/edit_file",
    description=_edit_file_description,
)
async def edit_file(
    path: FilePathArg,
    old: OldTextArg,
    new: NewTextArg,
    replace_all: ReplaceAllArg = False,
) -> EditFileOutput:
    """Replace exact text in a file."""
    return await asyncio.to_thread(
        edit_file_execute, path, old, new, replace_all
    )


@local_tool(http_method="POST", http_path="/tools/multi_edit_file")
async def multi_edit_file(
    path: FilePathArg, edits: EditsArg
) -> MultiEditFileOutput:
    """Apply multiple exact-text edits to one file."""
    return await asyncio.to_thread(multi_edit_file_execute, path, edits)


@local_tool(http_method="POST", http_path="/tools/delete")
async def delete_file_or_dir(
    path: FilePathArg, recursive: RecursiveArg = False
) -> DeleteFileOrDirOutput:
    """Delete a file or directory inside the controlled workspace/container."""
    return await asyncio.to_thread(delete_file_or_dir_execute, path, recursive)
