"""Search and tree-view tool registry."""

from __future__ import annotations

import asyncio

from ...ops.fs_ops import glob_paths
from ...ops.search_ops import grep, tree
from ..contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry


class SearchToolRegistry(DeclarativeToolRegistry):
    """Register search and tree-view tools."""

    name = "search_ops"


local_tool = SearchToolRegistry.get_tool_decorator()


def _tree_view_description(context: McpToolContext) -> str:
    settings = context.settings
    return (
        "Return a compact directory tree rooted at cwd. Use to understand project layout before reading files or making edits. "
        "Parameters: cwd defaults to '.' and is workspace-relative unless an allowed absolute path is supplied; depth defaults to 3 and controls nesting; "
        f"max_entries defaults to 500 and is capped by max_tree_entries={settings.max_tree_entries}. Prefer this over recursive list_files for high-level orientation."
    )


def _glob_search_description(context: McpToolContext) -> str:
    settings = context.settings
    return (
        "Find files by glob pattern. Use when you know filename patterns such as *.py or **/pyproject.toml and need matching paths, not file contents. "
        "Parameters: pattern is the glob expression; cwd defaults to '.' and narrows the search root; "
        f"max_results defaults to 500 and is capped by max_glob_results={settings.max_glob_results}."
    )


def _grep_search_description(context: McpToolContext) -> str:
    settings = context.settings
    return (
        "Search file contents with ripgrep. Use to locate symbols, usages, error messages, or text before reading or editing files. "
        "Parameters: query is a regular expression by default; set regex=false for literal text; cwd defaults to '.' and narrows the search root; glob optionally filters files; case_sensitive defaults to true; "
        f"max_results is optional and capped by max_grep_results={settings.max_grep_results}."
    )


@local_tool(
    http_method="POST",
    http_path="/tools/tree",
    description=_tree_view_description,
)
async def tree_view(
    cwd: str = ".", depth: int = 3, max_entries: int = 500
) -> dict:
    """Return a compact directory tree rooted at cwd."""
    return await tree(cwd, depth, max_entries)


@local_tool(
    http_method="POST",
    http_path="/tools/glob",
    description=_glob_search_description,
)
async def glob_search(
    pattern: str, cwd: str = ".", max_results: int = 500
) -> dict:
    """Find files by glob pattern."""
    return {
        "paths": await asyncio.to_thread(glob_paths, pattern, cwd, max_results)
    }


@local_tool(
    http_method="POST",
    http_path="/tools/grep",
    description=_grep_search_description,
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
    return await grep(query, cwd, glob, regex, case_sensitive, max_results)
