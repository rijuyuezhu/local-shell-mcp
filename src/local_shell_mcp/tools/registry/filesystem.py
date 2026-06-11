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
}


class FilesystemToolRegistry(ToolRegistry):
    """Register filesystem, search, patch, and safety tools."""

    name = "filesystem"

    def http_routes(self):
        return FILESYSTEM_HTTP_ROUTES

    def http_handlers(self):
        return FILESYSTEM_HTTP_HANDLERS

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_filesystem_mcp(mcp, context)


def register_filesystem_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register MCP tools for this tool group."""
    protected_meta = context.protected_meta

    @mcp.tool(meta=protected_meta)
    async def list_files(
        path: str = ".", recursive: bool = False, max_entries: int = 500
    ) -> dict:
        """List files and directories under a path. Use for quick directory inspection when a compact listing is enough. Parameters: path defaults to '.' and is workspace-relative unless an allowed absolute path is supplied; recursive defaults to false and lists one level, while true walks descendants; max_entries defaults to 500 and is capped by the server max_directory_entries setting."""
        try:
            return ok_response(
                await to_thread(list_dir, path, recursive, max_entries)
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=protected_meta)
    async def tree_view(
        cwd: str = ".", depth: int = 3, max_entries: int = 500
    ) -> dict:
        """Return a compact directory tree rooted at cwd. Use to understand project layout before reading files or making edits. Parameters: cwd defaults to '.' and is workspace-relative unless an allowed absolute path is supplied; depth defaults to 3 and controls nesting; max_entries defaults to 500 and is capped by the server max_tree_entries setting. Prefer this over recursive list_files for high-level orientation."""
        try:
            return ok_response(await tree(cwd, depth, max_entries))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=protected_meta)
    async def glob_search(
        pattern: str, cwd: str = ".", max_results: int = 500
    ) -> dict:
        """Find files by glob pattern. Use when you know filename patterns such as *.py or **/pyproject.toml and need matching paths, not file contents. Parameters: pattern is the glob expression; cwd defaults to '.' and narrows the search root; max_results defaults to 500 and is capped by the server max_glob_results setting."""
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

    @mcp.tool(meta=protected_meta)
    async def grep_search(
        query: str,
        cwd: str = ".",
        glob: str | None = None,
        regex: bool = True,
        case_sensitive: bool = True,
        max_results: int | None = None,
    ) -> dict:
        """Search file contents with ripgrep. Use to locate symbols, usages, error messages, or text before reading or editing files. Parameters: query is a regular expression by default; set regex=false for literal text; cwd defaults to '.' and narrows the search root; glob optionally filters files; case_sensitive defaults to true; max_results is optional and capped by the server max_grep_results setting."""
        try:
            return ok_response(
                await grep(query, cwd, glob, regex, case_sensitive, max_results)
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=protected_meta)
    async def read_file(
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        binary_preview: str | None = None,
        binary_preview_bytes: int = 256,
    ) -> dict:
        """Read a UTF-8 text file, optionally by line range. Use after locating a file to inspect exact content before editing. Parameters: path is required and workspace-relative unless an allowed absolute path is supplied; start_line and end_line are optional 1-based inclusive line numbers for paging large files; binary_preview optionally requests bounded binary preview behavior; binary_preview_bytes defaults to 256. Per-file bytes are capped by max_file_read_bytes."""
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

    @mcp.tool(meta=protected_meta)
    async def read_many_files(
        paths: list[str],
        start_line: int | None = None,
        end_line: int | None = None,
        binary_preview: str | None = None,
        binary_preview_bytes: int = 256,
    ) -> dict:
        """Read multiple UTF-8 text files with the same optional line range. Use when comparing related small files or collecting context across a few known paths. The server enforces file-count and total-byte limits; use targeted reads rather than broad path lists."""
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

    @mcp.tool(meta=protected_meta)
    async def write_file(
        path: str, content: str, overwrite: bool = True
    ) -> dict:
        """Write a UTF-8 text file. Use to create a new file or intentionally replace a whole file. Parameters: path is required and workspace-relative unless an allowed absolute path is supplied; content is the full file content and is capped by max_file_write_bytes; overwrite defaults to true and allows replacing existing content; set overwrite=false when creating only if absent. For precise modifications to existing files, prefer edit_file or apply_patch."""
        try:
            return ok_response(
                await to_thread(write_text, path, content, overwrite)
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=protected_meta)
    async def edit_file(
        path: str, old: str, new: str, replace_all: bool = False
    ) -> dict:
        """Replace exact text in a file. Use for small precise edits after reading the target file. Parameters: path is required; old must match exactly, including whitespace and indentation, and should be non-empty; new is the replacement text; replace_all defaults to false so one exact occurrence is expected, and should be true only when every exact occurrence should change. Write size is capped by max_file_write_bytes. For larger or multi-file diffs, prefer apply_patch."""
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

    @mcp.tool(meta=protected_meta)
    async def apply_patch(patch: str, cwd: str = ".") -> dict:
        """Apply a unified diff using git apply. Use for larger edits, multi-file changes, file additions, and deletions when an exact patch is clearer than individual replacements. cwd controls where paths in the patch are resolved. This uses git apply as a patch engine; for git workflow commands such as status, diff, add, commit, or push, use run_shell_tool."""
        try:
            return ok_response(await apply_patch_text(patch, cwd))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=protected_meta)
    async def secret_scan(
        cwd: str = ".", glob: str | None = None, max_results: int = 200
    ) -> dict:
        """Scan workspace text files for common secrets before commit, push, release, or sharing logs. Use as a precaution after editing configuration, credentials, CI, deployment, or documentation files. glob can narrow the scan and max_results bounds findings. Results are heuristic and do not prove the workspace is secret-free."""
        try:
            return ok_response(await run_secret_scan(cwd, glob, max_results))
        except Exception as exc:
            return handled_error(exc)
