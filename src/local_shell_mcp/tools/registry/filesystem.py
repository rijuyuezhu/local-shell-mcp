"""Filesystem/search MCP tool registry."""

from __future__ import annotations

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
from ..base import HttpToolRoute, McpToolContext, ToolRegistry
from .common import (
    _apply_patch_text,
    _handled_error,
    _ok,
    _read_audit_tail_entries,
    _read_many_files_sync,
    _secret_scan,
    _to_thread,
)


class FilesystemToolRegistry(ToolRegistry):
    """Register filesystem, search, patch, and audit tools."""

    name = "filesystem"

    def http_routes(self):
        from ..local_invocations import HTTP_TOOL_ROUTES

        names = {
            "list_files",
            "tree_view",
            "glob_search",
            "grep_search",
            "read_file",
            "read_many_files",
            "write_file",
            "edit_file",
            "multi_edit_file",
            "delete_file_or_dir",
            "apply_patch",
            "secret_scan",
            "audit_tail",
        }
        return (
            HttpToolRoute(method=method, path=path, tool_name=tool_name)
            for (method, path), tool_name in HTTP_TOOL_ROUTES.items()
            if tool_name in names
        )

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
            return _ok(await _to_thread(list_dir, path, recursive, max_entries))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def tree_view(
        cwd: str = ".", depth: int = 3, max_entries: int = 500
    ) -> dict:
        """Return a compact directory tree."""
        try:
            return _ok(await tree(cwd, depth, max_entries))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def glob_search(
        pattern: str, cwd: str = ".", max_results: int = 500
    ) -> dict:
        """Find files by glob pattern."""
        try:
            return _ok(
                {
                    "paths": await _to_thread(
                        glob_paths, pattern, cwd, max_results
                    )
                }
            )
        except Exception as exc:
            return _handled_error(exc)

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
            return _ok(
                await grep(query, cwd, glob, regex, case_sensitive, max_results)
            )
        except Exception as exc:
            return _handled_error(exc)

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
            return _ok(
                await _to_thread(
                    read_text,
                    path,
                    start_line,
                    end_line,
                    binary_preview,
                    binary_preview_bytes,
                )
            )
        except Exception as exc:
            return _handled_error(exc)

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
            return _ok(
                await _to_thread(
                    _read_many_files_sync,
                    paths,
                    start_line,
                    end_line,
                    binary_preview,
                    binary_preview_bytes,
                )
            )
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def write_file(
        path: str, content: str, overwrite: bool = True
    ) -> dict:
        """Write a UTF-8 text file."""
        try:
            return _ok(await _to_thread(write_text, path, content, overwrite))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def edit_file(
        path: str, old: str, new: str, replace_all: bool = False
    ) -> dict:
        """Replace exact text in a file. Use this for precise code edits."""
        try:
            return _ok(await _to_thread(edit_text, path, old, new, replace_all))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def multi_edit_file(path: str, edits: list[dict]) -> dict:
        """Apply multiple exact-text edits to one file. Each edit has old, new, replace_all."""
        try:
            return _ok(await _to_thread(multi_edit_text, path, edits))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def delete_file_or_dir(path: str, recursive: bool = False) -> dict:
        """Delete a file or directory inside the controlled workspace/container."""
        try:
            return _ok(await _to_thread(delete_path, path, recursive))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def apply_patch(patch: str, cwd: str = ".") -> dict:
        """Apply a unified diff using git apply."""
        try:
            return _ok(await _apply_patch_text(patch, cwd))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def secret_scan(
        cwd: str = ".", glob: str | None = None, max_results: int = 200
    ) -> dict:
        """Scan workspace text files for common secrets before commit/push."""
        try:
            return _ok(await _secret_scan(cwd, glob, max_results))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def audit_tail(lines: int = 100) -> dict:
        """Read recent audit log entries."""
        try:
            return _ok(await _to_thread(_read_audit_tail_entries, lines))
        except Exception as exc:
            return _handled_error(exc)
