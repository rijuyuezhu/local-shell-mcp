"""File operation tool registry."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...ops.fs_ops import (
    delete_path,
    edit_text,
    list_dir,
    multi_edit_text,
    read_many_files_sync,
    read_text,
    write_text,
)
from ..base import (
    HttpToolRoute,
    McpToolContext,
    StaticHttpToolRegistry,
    ToolHandler,
)
from ..responses import handled_error, ok_response, to_thread


async def _list_files(args: dict[str, Any]) -> list[dict[str, Any]]:
    return await to_thread(
        list_dir,
        args.get("path", "."),
        args.get("recursive", False),
        args.get("max_entries", 500),
    )


async def _read_file(args: dict[str, Any]) -> dict[str, Any]:
    return await to_thread(
        read_text,
        args["path"],
        args.get("start_line"),
        args.get("end_line"),
        args.get("binary_preview"),
        args.get("binary_preview_bytes", 256),
    )


async def _read_many_files(args: dict[str, Any]) -> dict[str, Any]:
    return await to_thread(
        read_many_files_sync,
        args["paths"],
        args.get("start_line"),
        args.get("end_line"),
        args.get("binary_preview"),
        args.get("binary_preview_bytes", 256),
    )


async def _write_file(args: dict[str, Any]) -> dict[str, Any]:
    return await to_thread(
        write_text, args["path"], args["content"], args.get("overwrite", True)
    )


async def _edit_file(args: dict[str, Any]) -> dict[str, Any]:
    return await to_thread(
        edit_text,
        args["path"],
        args["old"],
        args["new"],
        args.get("replace_all", False),
    )


async def _multi_edit_file(args: dict[str, Any]) -> dict[str, Any]:
    return await to_thread(multi_edit_text, args["path"], args["edits"])


async def _delete_file_or_dir(args: dict[str, Any]) -> dict[str, Any]:
    return await to_thread(
        delete_path, args["path"], args.get("recursive", False)
    )


FILE_HTTP_ROUTES = (
    HttpToolRoute("POST", "/tools/list_files", "list_files"),
    HttpToolRoute("POST", "/tools/read_file", "read_file"),
    HttpToolRoute("POST", "/tools/read_many_files", "read_many_files"),
    HttpToolRoute("POST", "/tools/write_file", "write_file"),
    HttpToolRoute("POST", "/tools/edit_file", "edit_file"),
    HttpToolRoute("POST", "/tools/multi_edit_file", "multi_edit_file"),
    HttpToolRoute("POST", "/tools/delete", "delete_file_or_dir"),
)

FILE_HTTP_HANDLERS: dict[str, ToolHandler] = {
    "list_files": _list_files,
    "read_file": _read_file,
    "read_many_files": _read_many_files,
    "write_file": _write_file,
    "edit_file": _edit_file,
    "multi_edit_file": _multi_edit_file,
    "delete_file_or_dir": _delete_file_or_dir,
}


class FileToolRegistry(StaticHttpToolRegistry):
    """Register file operation tools."""

    name = "files"

    routes = FILE_HTTP_ROUTES
    handlers = FILE_HTTP_HANDLERS

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_file_mcp(mcp, context)


def register_file_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register file operation MCP tools."""
    protected_meta = context.protected_meta
    settings = context.settings

    @mcp.tool(
        meta=protected_meta,
        description=(
            "List files and directories under a path. Use for quick directory inspection when a compact listing is enough. "
            "Parameters: path defaults to '.' and is workspace-relative unless an allowed absolute path is supplied; recursive defaults to false and lists one level, while true walks descendants; "
            f"max_entries defaults to 500 and is capped by max_directory_entries={settings.max_directory_entries}."
        ),
    )
    async def list_files(
        path: str = ".", recursive: bool = False, max_entries: int = 500
    ) -> dict:
        """List files and directories under a path."""
        try:
            return ok_response(
                await to_thread(list_dir, path, recursive, max_entries)
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(
        meta=protected_meta,
        description=(
            "Read a UTF-8 text file, optionally by line range. Use after locating a file to inspect exact content before editing. "
            "Parameters: path is required and workspace-relative unless an allowed absolute path is supplied; start_line and end_line are optional 1-based inclusive line numbers for paging large files; "
            f"binary_preview optionally requests bounded binary preview behavior; binary_preview_bytes defaults to 256. Per-file bytes are capped by max_file_read_bytes={settings.max_file_read_bytes}."
        ),
    )
    async def read_file(
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        binary_preview: str | None = None,
        binary_preview_bytes: int = 256,
    ) -> dict:
        """Read a UTF-8 text file, optionally by line range."""
        try:
            return ok_response(
                await to_thread(
                    read_text,
                    path,
                    start_line,
                    end_line,
                    binary_preview,
                    binary_preview_bytes,
                )
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(
        meta=protected_meta,
        description=(
            "Read multiple UTF-8 text files with the same optional line range. Use when comparing related small files or collecting context across a few known paths. "
            f"The server enforces max_read_many_files={settings.max_read_many_files} and max_read_many_total_bytes={settings.max_read_many_total_bytes}; use targeted reads rather than broad path lists."
        ),
    )
    async def read_many_files(
        paths: list[str],
        start_line: int | None = None,
        end_line: int | None = None,
        binary_preview: str | None = None,
        binary_preview_bytes: int = 256,
    ) -> dict:
        """Read multiple UTF-8 text files with the same optional line range."""
        try:
            return ok_response(
                await to_thread(
                    read_many_files_sync,
                    paths,
                    start_line,
                    end_line,
                    binary_preview,
                    binary_preview_bytes,
                )
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(
        meta=protected_meta,
        description=(
            "Write a UTF-8 text file. Use to create a new file or intentionally replace a whole file. "
            "Parameters: path is required and workspace-relative unless an allowed absolute path is supplied; content is the full file content; "
            f"writes are capped by max_file_write_bytes={settings.max_file_write_bytes}; overwrite defaults to true and allows replacing existing content; set overwrite=false when creating only if absent. "
            "For precise modifications to existing files, prefer edit_file or apply_patch."
        ),
    )
    async def write_file(
        path: str, content: str, overwrite: bool = True
    ) -> dict:
        """Write a UTF-8 text file."""
        try:
            return ok_response(
                await to_thread(write_text, path, content, overwrite)
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(
        meta=protected_meta,
        description=(
            "Replace exact text in a file. Use for small precise edits after reading the target file. "
            "Parameters: path is required; old must match exactly, including whitespace and indentation, and should be non-empty; new is the replacement text; "
            f"replace_all defaults to false so one exact occurrence is expected, and should be true only when every exact occurrence should change. Writes are capped by max_file_write_bytes={settings.max_file_write_bytes}. "
            "For larger or multi-file diffs, prefer apply_patch."
        ),
    )
    async def edit_file(
        path: str, old: str, new: str, replace_all: bool = False
    ) -> dict:
        """Replace exact text in a file."""
        try:
            return ok_response(
                await to_thread(edit_text, path, old, new, replace_all)
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=protected_meta)
    async def multi_edit_file(path: str, edits: list[dict]) -> dict:
        """Apply multiple exact-text edits to one file. Use when several small replacements in the same file should be made together. Each edit must provide old, new, and optional replace_all; each old string must match exactly. Read the file first to avoid stale or ambiguous edits."""
        try:
            return ok_response(await to_thread(multi_edit_text, path, edits))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=protected_meta)
    async def delete_file_or_dir(path: str, recursive: bool = False) -> dict:
        """Delete a file or directory inside the controlled workspace/container. Use only when removal is intentional. recursive=false deletes files or empty directories; recursive=true is required for non-empty directories and should be used carefully."""
        try:
            return ok_response(await to_thread(delete_path, path, recursive))
        except Exception as exc:
            return handled_error(exc)
