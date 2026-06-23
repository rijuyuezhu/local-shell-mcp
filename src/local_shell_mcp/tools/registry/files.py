"""File operation tool registry."""

import asyncio

from pydantic import TypeAdapter

from ...ops.files import (
    delete_file_or_dir_execute,
    edit_file_execute,
    edit_lines_execute,
    list_files_execute,
    multi_edit_file_execute,
    read_file_execute,
    read_many_files_execute,
    write_file_execute,
)
from ...schemas.input_models.files import (
    EditEndLineArg,
    EditsArg,
    EditStartLineArg,
    EndLineArg,
    FileContentArg,
    FilePathArg,
    LineReplacementArg,
    ListPathArg,
    MaxEntriesArg,
    NewTextArg,
    OldTextArg,
    OverwriteArg,
    ReadFilesArg,
    RecursiveArg,
    ReplaceAllArg,
    SnapshotIdArg,
    StartLineArg,
    ToolSessionIdArg,
)
from ...schemas.result_models.files import (
    DeleteFileOrDirOutput,
    EditFileOutput,
    EditLinesOutput,
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
    return f"""Lower-level UTF-8 file read with optional start/end lines. Prefer high-level `read(path)` for normal agent context because selectors travel with the path. The result includes raw `content`, original line objects, model-facing `numbered_content`, `snapshot_id`, `file_sha256`, and displayed `seen_ranges`. Use the snapshot with `edit_lines` and re-read before editing unshown ranges. Current per-file read cap: {settings.max_file_read_bytes} bytes."""


def _read_many_files_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Lower-level batch read for multiple known UTF-8 files and optional line ranges. Use when independent reads should be batched; otherwise prefer high-level `read(path)` for selector-based single targets. Each file result includes numbered content and snapshot metadata suitable for `edit_lines` grounding. Current limits: {settings.max_read_many_files} files and {settings.max_read_many_total_bytes} returned bytes."""


def _write_file_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Write a complete UTF-8 file. Use for new files or intentional whole-file replacement. For precise modifications to existing files, prefer grounded `edit_lines`; use exact-text edit or patch tools only when clearer. Do not replace an existing file wholesale unless that is the intended edit. Current write cap: {settings.max_file_write_bytes} bytes."""


def _edit_file_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Lower-level exact-text replacement in a UTF-8 file. Prefer `edit_lines` when a recent read/search provided line numbers and snapshot metadata. Use exact-text replacement for small, unique text changes where line grounding is awkward, and include enough surrounding text to make the match unique unless intentionally replacing all matches. Current write cap: {settings.max_file_write_bytes} bytes."""


def _edit_lines_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Replace an inclusive 1-based whole-line range in a UTF-8 file, grounded by a recent read/search snapshot. Prefer this for normal code edits after `read`, `search`, `read_file`, or `read_many_files` displayed the target lines. Pass `snapshot_id` from the grounding result and the same `session_id` when present. `replacement` is the final content for the range. Keep ranges tight, edit only displayed lines, and use the fresh numbered context returned by a successful edit before the next edit. Current write cap: {settings.max_file_write_bytes} bytes."""


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
    http_path="/tools/read_file",
    description=_read_file_description,
    mcp_scopes=("shell:read",),
)
async def read_file(
    path: FilePathArg,
    start_line: StartLineArg = None,
    end_line: EndLineArg = None,
    session_id: ToolSessionIdArg = None,
) -> ReadFileOutput:
    """Read a UTF-8 text file, optionally by line range."""
    return await asyncio.to_thread(
        read_file_execute,
        path,
        start_line,
        end_line,
        session_id,
    )


@local_tool(
    http_method="POST",
    http_path="/tools/read_many_files",
    description=_read_many_files_description,
    mcp_scopes=("shell:read",),
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
    mcp_scopes=("shell:read", "shell:write"),
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
    mcp_scopes=("shell:read", "shell:write"),
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
    snapshot_id: SnapshotIdArg = None,
    session_id: ToolSessionIdArg = None,
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
    http_path="/tools/multi_edit_file",
    mcp_scopes=("shell:read", "shell:write"),
)
async def multi_edit_file(
    path: FilePathArg, edits: EditsArg
) -> MultiEditFileOutput:
    """Apply multiple exact-text edits to one file."""
    return await asyncio.to_thread(multi_edit_file_execute, path, edits)


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
