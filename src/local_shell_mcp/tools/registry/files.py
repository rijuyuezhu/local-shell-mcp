"""File operation tool registry."""

import asyncio

from ...ops.files import (
    delete_file_or_dir_execute,
    edit_lines_execute,
    list_files_execute,
    write_file_execute,
)
from ...schemas.input_models.files import (
    EditEndLineArg,
    EditStartLineArg,
    FileContentArg,
    FilePathArg,
    LineReplacementArg,
    ListPathArg,
    MaxEntriesArg,
    OverwriteArg,
    RecursiveArg,
    SnapshotIdArg,
)
from ...schemas.input_models.session import SessionIdArg
from ...schemas.result_models.files import (
    DeleteFileOrDirOutput,
    EditLinesOutput,
    ListFilesOutput,
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


def _write_file_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Write a complete UTF-8 file. Use for new files or intentional whole-file replacement. For precise modifications to existing files, prefer grounded `edit_lines`; use exact-text edit or patch tools only when clearer. Do not replace an existing file wholesale unless that is the intended edit. Current write cap: {settings.max_file_write_bytes} bytes."""


def _edit_lines_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Replace an inclusive 1-based whole-line range in a UTF-8 file, grounded by a recent read/search snapshot. Prefer this for normal code edits after `read` or `search` displayed the target lines. Pass `snapshot_id` from the grounding result and the same `session_id` when present. `replacement` is the final content for the range. Keep ranges tight, edit only displayed lines, and use the fresh numbered context returned by a successful edit before the next edit. Current write cap: {settings.max_file_write_bytes} bytes."""


@local_tool(
    http_method="POST",
    http_path="/tools/list_files",
    description=_list_files_description,
    mcp_scopes=("shell:read",),
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
    http_path="/tools/write_file",
    description=_write_file_description,
    mcp_scopes=("shell:read", "shell:write"),
)
async def write_file(
    path: FilePathArg, content: FileContentArg, overwrite: OverwriteArg = True
) -> WriteFileOutput:
    """Write a UTF-8 text file."""
    return await asyncio.to_thread(write_file_execute, path, content, overwrite)


@local_tool(
    http_method="POST",
    http_path="/tools/edit_lines",
    description=_edit_lines_description,
    mcp_scopes=("shell:read", "shell:write"),
)
async def edit_lines(
    path: FilePathArg,
    start_line: EditStartLineArg,
    end_line: EditEndLineArg,
    replacement: LineReplacementArg,
    session_id: SessionIdArg,
    snapshot_id: SnapshotIdArg = None,
) -> EditLinesOutput:
    """Replace an inclusive whole-line range in a file."""
    return await asyncio.to_thread(
        edit_lines_execute,
        path,
        start_line,
        end_line,
        replacement,
        snapshot_id,
        session_id,
    )


@local_tool(
    http_method="POST",
    http_path="/tools/delete",
    mcp_scopes=("shell:read", "shell:write"),
)
async def delete_file_or_dir(
    path: FilePathArg, recursive: RecursiveArg = False
) -> DeleteFileOrDirOutput:
    """Delete a file or directory inside the controlled workspace/container."""
    return await asyncio.to_thread(delete_file_or_dir_execute, path, recursive)
