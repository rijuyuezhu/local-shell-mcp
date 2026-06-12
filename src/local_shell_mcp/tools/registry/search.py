"""Search and tree-view tool registry."""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from ...ops.fs_ops import glob_paths
from ...ops.search_ops import grep, tree
from ..base import (
    HttpToolRoute,
    McpToolContext,
    StaticHttpToolRegistry,
    ToolHandler,
)
from ..responses import handled_error, ok_response


async def _tree_view(args: dict[str, Any]) -> dict[str, Any]:
    return await tree(
        args.get("cwd", "."),
        args.get("depth", 3),
        args.get("max_entries", 500),
    )


async def _glob_search(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "paths": await asyncio.to_thread(
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


SEARCH_HTTP_ROUTES = (
    HttpToolRoute("POST", "/tools/tree", "tree_view"),
    HttpToolRoute("POST", "/tools/glob", "glob_search"),
    HttpToolRoute("POST", "/tools/grep", "grep_search"),
)

SEARCH_HTTP_HANDLERS: dict[str, ToolHandler] = {
    "tree_view": _tree_view,
    "glob_search": _glob_search,
    "grep_search": _grep_search,
}


class SearchToolRegistry(StaticHttpToolRegistry):
    """Register search and tree-view tools."""

    name = "search_ops"

    routes = SEARCH_HTTP_ROUTES
    handlers = SEARCH_HTTP_HANDLERS

    def register_mcp(self, mcp: FastMCP, context: McpToolContext) -> None:
        register_search_mcp(mcp, context)


def register_search_mcp(mcp: FastMCP, context: McpToolContext) -> None:
    """Register search MCP tools."""
    protected_meta = context.protected_meta
    settings = context.settings

    @mcp.tool(
        meta=protected_meta,
        description=(
            "Return a compact directory tree rooted at cwd. Use to understand project layout before reading files or making edits. "
            "Parameters: cwd defaults to '.' and is workspace-relative unless an allowed absolute path is supplied; depth defaults to 3 and controls nesting; "
            f"max_entries defaults to 500 and is capped by max_tree_entries={settings.max_tree_entries}. Prefer this over recursive list_files for high-level orientation."
        ),
    )
    async def tree_view(
        cwd: str = ".", depth: int = 3, max_entries: int = 500
    ) -> dict:
        """Return a compact directory tree rooted at cwd."""
        try:
            return ok_response(await tree(cwd, depth, max_entries))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(
        meta=protected_meta,
        description=(
            "Find files by glob pattern. Use when you know filename patterns such as *.py or **/pyproject.toml and need matching paths, not file contents. "
            "Parameters: pattern is the glob expression; cwd defaults to '.' and narrows the search root; "
            f"max_results defaults to 500 and is capped by max_glob_results={settings.max_glob_results}."
        ),
    )
    async def glob_search(
        pattern: str, cwd: str = ".", max_results: int = 500
    ) -> dict:
        """Find files by glob pattern."""
        try:
            return ok_response(
                {
                    "paths": await asyncio.to_thread(
                        glob_paths, pattern, cwd, max_results
                    )
                }
            )
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(
        meta=protected_meta,
        description=(
            "Search file contents with ripgrep. Use to locate symbols, usages, error messages, or text before reading or editing files. "
            "Parameters: query is a regular expression by default; set regex=false for literal text; cwd defaults to '.' and narrows the search root; glob optionally filters files; case_sensitive defaults to true; "
            f"max_results is optional and capped by max_grep_results={settings.max_grep_results}."
        ),
    )
    async def grep_search(
        query: str,
        cwd: str = ".",
        glob: str | None = None,
        regex: bool = True,
        case_sensitive: bool = True,
        max_results: int | None = None,
    ) -> dict:
        """Search file contents with ripgrep."""
        try:
            return ok_response(
                await grep(query, cwd, glob, regex, case_sensitive, max_results)
            )
        except Exception as exc:
            return handled_error(exc)
