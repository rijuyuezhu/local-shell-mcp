"""Search and tree-view tool registry."""

import asyncio

from ...ops.search import (
    glob_search_execute,
    grep_search_execute,
    tree_view_execute,
)
from ...schemas.input_models.search import (
    CaseSensitiveArg,
    GlobMaxResultsArg,
    GlobPatternArg,
    GrepGlobArg,
    GrepMaxResultsArg,
    GrepQueryArg,
    RegexArg,
    SearchCwdArg,
    TreeCwdArg,
    TreeDepthArg,
    TreeMaxEntriesArg,
)
from ...schemas.result_models.search import (
    GlobSearchOutput,
    GrepSearchOutput,
    TreeViewOutput,
)
from ..contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry


class SearchToolRegistry(DeclarativeToolRegistry):
    """Register search and tree-view tools."""

    name = "search"
    """Registry group name used for tool-surface organization."""


local_tool = SearchToolRegistry.get_tool_decorator()


def _tree_view_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Return a compact directory tree for high-level project orientation before targeted file reads. Current max tree entries: {settings.max_tree_entries}."""


def _glob_search_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Find files by glob pattern when you know filename patterns and need matching paths, not file contents. Current max glob results: {settings.max_glob_results}."""


def _grep_search_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Search file contents with ripgrep to locate symbols, usages, error messages, or text before reading or editing files. Current max_grep_results={settings.max_grep_results}."""


@local_tool(
    http_method="POST",
    http_path="/tools/tree",
    description=_tree_view_description,
)
async def tree_view(
    cwd: TreeCwdArg = ".",
    depth: TreeDepthArg = 3,
    max_entries: TreeMaxEntriesArg = 500,
) -> TreeViewOutput:
    """Return a compact directory tree rooted at cwd."""
    return await tree_view_execute(cwd, depth, max_entries)


@local_tool(
    http_method="POST",
    http_path="/tools/glob",
    description=_glob_search_description,
)
async def glob_search(
    pattern: GlobPatternArg,
    cwd: SearchCwdArg = ".",
    max_results: GlobMaxResultsArg = 500,
) -> GlobSearchOutput:
    """Find files by glob pattern."""
    return await asyncio.to_thread(
        glob_search_execute, pattern, cwd, max_results
    )


@local_tool(
    http_method="POST",
    http_path="/tools/grep",
    description=_grep_search_description,
)
async def grep_search(
    query: GrepQueryArg,
    cwd: SearchCwdArg = ".",
    glob: GrepGlobArg = None,
    regex: RegexArg = True,
    case_sensitive: CaseSensitiveArg = True,
    max_results: GrepMaxResultsArg = None,
) -> GrepSearchOutput:
    """Search file contents with ripgrep."""
    return await grep_search_execute(
        query, cwd, glob, regex, case_sensitive, max_results
    )
