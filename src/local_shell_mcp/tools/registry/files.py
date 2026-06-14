"""File operation tool registry."""

import asyncio
from typing import Any

from ...ops.fs_ops import (
    delete_file_or_dir_execute,
    edit_file_execute,
    list_files_execute,
    multi_edit_file_execute,
    read_file_execute,
    read_many_files_execute,
    write_file_execute,
)
from ..contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry


class FileToolRegistry(DeclarativeToolRegistry):
    """Register file operation tools."""

    name = "file"


local_tool = FileToolRegistry.get_tool_decorator()


def _list_files_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""List files and directories under a path. Use for quick directory inspection when a compact listing is enough. Parameters: path defaults to '.' and is workspace-relative unless an allowed absolute path is supplied; recursive defaults to false and lists one level, while true walks descendants. Limits: max_entries defaults to 500 and is capped by max_directory_entries={settings.max_directory_entries}."""


def _read_file_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Read a UTF-8 text file, optionally by line range. Use after locating a file to inspect exact content before editing. Parameters: path is required and workspace-relative unless an allowed absolute path is supplied; start_line and end_line are optional 1-based inclusive line numbers for paging large files. Binary preview: binary_preview requests bounded binary preview behavior; binary_preview_bytes defaults to 256. Limits: per-file bytes are capped by max_file_read_bytes={settings.max_file_read_bytes}."""


def _read_many_files_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Read multiple UTF-8 text files with the same optional line range. Use when comparing related small files or collecting context across a few known paths. Limits: max_read_many_files={settings.max_read_many_files}, max_read_many_total_bytes={settings.max_read_many_total_bytes}. Use targeted path lists."""


def _write_file_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Write a UTF-8 text file. Use to create a new file or intentionally replace a whole file. Parameters: path is required and workspace-relative unless an allowed absolute path is supplied; content is the full file content. Limits: writes are capped by max_file_write_bytes={settings.max_file_write_bytes}. Behavior: overwrite defaults to true and allows replacing existing content; set overwrite=false when creating only if absent. For precise modifications to existing files, use edit_file or apply_patch."""


def _edit_file_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Replace exact text in a file. Use for small precise edits after reading the target file. Parameters: path is required; old must match exactly, including whitespace and indentation, and should be non-empty; new is the replacement text. Behavior: replace_all defaults to false so one exact occurrence is expected, and should be true only when every exact occurrence should change. Limits: writes are capped by max_file_write_bytes={settings.max_file_write_bytes}. For larger or multi-file diffs, use apply_patch."""


@local_tool(
    http_method="POST",
    http_path="/tools/list_files",
    description=_list_files_description,
)
async def list_files(
    path: str = ".", recursive: bool = False, max_entries: int = 500
) -> list[dict[str, Any]]:
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
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    binary_preview: str | None = None,
    binary_preview_bytes: int = 256,
) -> dict:
    """Read a UTF-8 text file, optionally by line range."""
    return await asyncio.to_thread(
        read_file_execute,
        path,
        start_line,
        end_line,
        binary_preview,
        binary_preview_bytes,
    )


@local_tool(
    http_method="POST",
    http_path="/tools/read_many_files",
    description=_read_many_files_description,
)
async def read_many_files(
    paths: list[str],
    start_line: int | None = None,
    end_line: int | None = None,
    binary_preview: str | None = None,
    binary_preview_bytes: int = 256,
) -> dict:
    """Read multiple UTF-8 text files with the same optional line range."""
    return await asyncio.to_thread(
        read_many_files_execute,
        paths,
        start_line,
        end_line,
        binary_preview,
        binary_preview_bytes,
    )


@local_tool(
    http_method="POST",
    http_path="/tools/write_file",
    description=_write_file_description,
)
async def write_file(path: str, content: str, overwrite: bool = True) -> dict:
    """Write a UTF-8 text file."""
    return await asyncio.to_thread(write_file_execute, path, content, overwrite)


@local_tool(
    http_method="POST",
    http_path="/tools/edit_file",
    description=_edit_file_description,
)
async def edit_file(
    path: str, old: str, new: str, replace_all: bool = False
) -> dict:
    """Replace exact text in a file."""
    return await asyncio.to_thread(
        edit_file_execute, path, old, new, replace_all
    )


@local_tool(http_method="POST", http_path="/tools/multi_edit_file")
async def multi_edit_file(path: str, edits: list[dict]) -> dict:
    """Apply multiple exact-text edits to one file. Use when several small replacements in the same file should be made together. Each edit must provide old, new, and optional replace_all; each old string must match exactly. Read the file first to avoid stale or ambiguous edits."""
    return await asyncio.to_thread(multi_edit_file_execute, path, edits)


@local_tool(http_method="POST", http_path="/tools/delete")
async def delete_file_or_dir(path: str, recursive: bool = False) -> dict:
    """Delete a file or directory inside the controlled workspace/container. Use only when removal is intentional. recursive=false deletes files or empty directories; recursive=true is required for non-empty directories and should be used carefully."""
    return await asyncio.to_thread(delete_file_or_dir_execute, path, recursive)
