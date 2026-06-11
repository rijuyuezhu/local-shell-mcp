"""Filesystem/search MCP tool registry."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...ops.fs_ops import (
    delete_path,
    edit_text,
    glob_paths,
    list_dir,
    multi_edit_text,
    read_text,
    write_text,
)
from ...ops.search_ops import grep, tree
from ..base import HttpToolRoute, McpToolContext, ToolHandler, ToolRegistry
from .common import (
    apply_patch_text,
    handled_error,
    ok_response,
    read_audit_tail_entries,
    read_many_files_sync,
    run_secret_scan,
    to_thread,
)


async def _list_files(args: dict[str, Any]) -> list[dict[str, Any]]:
    return await to_thread(
        list_dir,
        args.get("path", "."),
        args.get("recursive", False),
        args.get("max_entries", 500),
    )


async def _tree_view(args: dict[str, Any]) -> dict[str, Any]:
    return await tree(
        args.get("cwd", "."),
        args.get("depth", 3),
        args.get("max_entries", 500),
    )


async def _glob_search(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "paths": await to_thread(
            glob_paths,
            args["pattern"],
            args.get("cwd", "."),
            args.get("max_results", 500),
        )
    }


async def _grep_search(args: dict[str, Any]) -> dict[str, Any]:
    return await grep(
        args["query"],
        args.get("cwd", "."),
        args.get("glob"),
        args.get("regex", True),
        args.get("case_sensitive", True),
        args.get("max_results"),
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


async def _apply_patch(args: dict[str, Any]) -> dict[str, Any]:
    return await apply_patch_text(args["patch"], args.get("cwd", "."))


async def _secret_scan(args: dict[str, Any]) -> dict[str, Any]:
    return await run_secret_scan(
        args.get("cwd", "."), args.get("glob"), args.get("max_results", 200)
    )


async def _audit_tail(args: dict[str, Any]) -> dict[str, Any]:
    return await to_thread(read_audit_tail_entries, args.get("lines", 100))


FILESYSTEM_HTTP_ROUTES = (
    HttpToolRoute("POST", "/tools/list_files", "list_files"),
    HttpToolRoute("POST", "/tools/tree", "tree_view"),
    HttpToolRoute("POST", "/tools/glob", "glob_search"),
    HttpToolRoute("POST", "/tools/grep", "grep_search"),
    HttpToolRoute("POST", "/tools/read_file", "read_file"),
    HttpToolRoute("POST", "/tools/write_file", "write_file"),
    HttpToolRoute("POST", "/tools/edit_file", "edit_file"),
    HttpToolRoute("POST", "/tools/multi_edit_file", "multi_edit_file"),
    HttpToolRoute("POST", "/tools/delete", "delete_file_or_dir"),
)

FILESYSTEM_HTTP_HANDLERS: dict[str, ToolHandler] = {
    "list_files": _list_files,
    "tree_view": _tree_view,
    "glob_search": _glob_search,
    "grep_search": _grep_search,
    "read_file": _read_file,
    "read_many_files": _read_many_files,
    "write_file": _write_file,
    "edit_file": _edit_file,
    "multi_edit_file": _multi_edit_file,
    "delete_file_or_dir": _delete_file_or_dir,
    "apply_patch": _apply_patch,
    "secret_scan": _secret_scan,
    "audit_tail": _audit_tail,
}


class FilesystemToolRegistry(ToolRegistry):
    """Register filesystem, search, patch, and audit tools."""

    name = "filesystem"

    def http_routes(self):
        return FILESYSTEM_HTTP_ROUTES

    def http_handlers(self):
        return FILESYSTEM_HTTP_HANDLERS

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_filesystem_mcp(mcp, context)


def register_filesystem_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register MCP tools for this tool group."""
    oauth_meta = context.oauth_meta

    @mcp.tool(meta=oauth_meta)
    async def list_files(
        path: str = ".", recursive: bool = False, max_entries: int = 500
    ) -> dict:
        """List files and directories."""
        try:
            return ok_response(
                await to_thread(list_dir, path, recursive, max_entries)
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def tree_view(
        cwd: str = ".", depth: int = 3, max_entries: int = 500
    ) -> dict:
        """Return a compact directory tree."""
        try:
            return ok_response(await tree(cwd, depth, max_entries))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def glob_search(
        pattern: str, cwd: str = ".", max_results: int = 500
    ) -> dict:
        """Find files by glob pattern."""
        try:
            return ok_response(
                {
                    "paths": await to_thread(
                        glob_paths, pattern, cwd, max_results
                    )
                }
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def grep_search(
        query: str,
        cwd: str = ".",
        glob: str | None = None,
        regex: bool = True,
        case_sensitive: bool = True,
        max_results: int | None = None,
    ) -> dict:
        """Search file contents using ripgrep."""
        try:
            return ok_response(
                await grep(query, cwd, glob, regex, case_sensitive, max_results)
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
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

    @mcp.tool(meta=oauth_meta)
    async def read_many_files(
        paths: list[str],
        start_line: int | None = None,
        end_line: int | None = None,
        binary_preview: str | None = None,
        binary_preview_bytes: int = 256,
    ) -> dict:
        """Read multiple UTF-8 text files."""
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

    @mcp.tool(meta=oauth_meta)
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

    @mcp.tool(meta=oauth_meta)
    async def edit_file(
        path: str, old: str, new: str, replace_all: bool = False
    ) -> dict:
        """Replace exact text in a file. Use this for precise code edits."""
        try:
            return ok_response(
                await to_thread(edit_text, path, old, new, replace_all)
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def multi_edit_file(path: str, edits: list[dict]) -> dict:
        """Apply multiple exact-text edits to one file. Each edit has old, new, replace_all."""
        try:
            return ok_response(await to_thread(multi_edit_text, path, edits))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def delete_file_or_dir(path: str, recursive: bool = False) -> dict:
        """Delete a file or directory inside the controlled workspace/container."""
        try:
            return ok_response(await to_thread(delete_path, path, recursive))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def apply_patch(patch: str, cwd: str = ".") -> dict:
        """Apply a unified diff using git apply."""
        try:
            return ok_response(await apply_patch_text(patch, cwd))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def secret_scan(
        cwd: str = ".", glob: str | None = None, max_results: int = 200
    ) -> dict:
        """Scan workspace text files for common secrets before commit/push."""
        try:
            return ok_response(await run_secret_scan(cwd, glob, max_results))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def audit_tail(lines: int = 100) -> dict:
        """Read recent audit log entries."""
        try:
            return ok_response(await to_thread(read_audit_tail_entries, lines))
        except Exception as exc:
            return handled_error(exc)
