"""File operation tool registry."""

from ...ops.files import (
    delete_file_or_dir_dispatch_execute,
    edit_lines_dispatch_execute,
    hashline_edit_dispatch_execute,
    list_files_dispatch_execute,
    write_file_dispatch_execute,
)
from ...schemas.input_models.files import (
    EditEndLineArg,
    EditStartLineArg,
    FileContentArg,
    FilePathArg,
    HashlineEditInputArg,
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
    return f"""List files and directories under a session workdir path for quick inspection. Relative paths resolve inside the explicit agent/workspace session. The result reports whether entries were truncated by the requested limit or server cap. Current max directory entries: {settings.max_directory_entries}."""


def _write_file_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Write a complete UTF-8 file inside an explicit agent/workspace session. Use for new files or intentional whole-file replacement. For ordinary edits to existing files, use hashline_edit from copied read/search rows instead of rewriting the file. Use edit_lines only when you already have exact structured path/start/end/replacement data. Use bash only when a command-driven transformation is clearer. Current write cap: {settings.max_file_write_bytes} bytes."""


def _edit_lines_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Low-level structured line edit for callers that already have exact path/start_line/end_line/replacement data. Do not use this as the normal model editing path from read/search output; use hashline_edit for copied `[path#snapshot_id]` plus `line:text` rows. If you do call edit_lines, pass the same session_id and the snapshot_id from the read/search result so stale files or unseen ranges are rejected. The range is inclusive, 1-based, and should cover only lines being changed; use an empty replacement to delete. Current write cap: {settings.max_file_write_bytes} bytes."""


def _hashline_edit_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Default model-facing edit tool for existing UTF-8 files. Copy the `[path#snapshot_id]` header and relevant `line:text` rows from the latest read/search output, then provide the final new content as `+text` rows. Supported single-hunk forms: copied rows followed by `+replacement` rows; copied rows with no `+` rows to delete; `SWAP start[-end]:` followed by `+replacement` rows; and `INSERT [BEFORE|AFTER] line:` followed by `+inserted` rows. Body rows are final content only: use `+` for blank lines, preserve indentation after `+`, and do not write `-old` rows or bare context lines. Line numbers refer to the original displayed snapshot; stale files, wrong paths, or unseen ranges are rejected. After a successful edit, use the returned fresh context or re-read before the next edit. Current write cap: {settings.max_file_write_bytes} bytes."""


@local_tool(
    http_method="POST",
    http_path="/tools/list_files",
    description=_list_files_description,
    mcp_scopes=("shell:read",),
)
async def list_files(
    session_id: SessionIdArg,
    path: ListPathArg = ".",
    recursive: RecursiveArg = False,
    max_entries: MaxEntriesArg = 500,
) -> ListFilesOutput:
    """List files and directories under a session workdir path."""
    return await list_files_dispatch_execute(
        path, recursive, max_entries, session_id
    )


@local_tool(
    http_method="POST",
    http_path="/tools/write_file",
    description=_write_file_description,
    mcp_scopes=("shell:read", "shell:write"),
)
async def write_file(
    session_id: SessionIdArg,
    path: FilePathArg,
    content: FileContentArg,
    overwrite: OverwriteArg = True,
) -> WriteFileOutput:
    """Write a UTF-8 text file inside a session workdir."""
    return await write_file_dispatch_execute(
        path, content, overwrite, session_id
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
    session_id: SessionIdArg,
    snapshot_id: SnapshotIdArg = None,
) -> EditLinesOutput:
    """Replace an inclusive whole-line range in a file."""
    return await edit_lines_dispatch_execute(
        path,
        start_line,
        end_line,
        replacement,
        snapshot_id,
        session_id,
    )


@local_tool(
    http_method="POST",
    http_path="/tools/hashline_edit",
    description=_hashline_edit_description,
    mcp_scopes=("shell:read", "shell:write"),
)
async def hashline_edit(
    session_id: SessionIdArg,
    input: HashlineEditInputArg,
) -> EditLinesOutput:
    """Apply a compact hashline edit copied from read/search output."""
    return await hashline_edit_dispatch_execute(input, session_id)


@local_tool(
    http_method="POST",
    http_path="/tools/delete",
    mcp_scopes=("shell:read", "shell:write"),
)
async def delete_file_or_dir(
    session_id: SessionIdArg, path: FilePathArg, recursive: RecursiveArg = False
) -> DeleteFileOrDirOutput:
    """Delete a file or directory inside a session workdir."""
    return await delete_file_or_dir_dispatch_execute(
        path, recursive, session_id
    )
