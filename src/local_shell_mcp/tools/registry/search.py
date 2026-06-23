"""Search and tree-view tool registry."""

import asyncio

from ...ops.search import (
    glob_search_execute,
    search_execute,
    tree_view_execute,
)
from ...schemas.input_models.files import ToolSessionIdArg
from ...schemas.input_models.search import (
    CaseSensitiveArg,
    GlobMaxResultsArg,
    GlobPatternArg,
    GrepMaxResultsArg,
    GrepQueryArg,
    RegexArg,
    SearchCwdArg,
    SearchPathsArg,
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


def _search_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Search code content using an oh-my-pi-style facade. Use built-in search for content discovery so results carry grounding metadata. pattern is text or regex depending on regex; paths scopes to files, directories, or globs. Results include numbered match lines, grouped context, snapshot metadata, and displayed ranges that can ground edit_lines. Current max_grep_results={settings.max_grep_results}."""


@local_tool(
    http_method="POST",
    http_path="/tools/tree",
    description=_tree_view_description,
    mcp_scopes=("shell:read",),
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
    mcp_scopes=("shell:read",),
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
    http_path="/tools/search",
    description=_search_description,
    annotations="read_only",
    mcp_scopes=("shell:read",),
)
async def search(
    pattern: GrepQueryArg,
    paths: SearchPathsArg = None,
    regex: RegexArg = True,
    case_sensitive: CaseSensitiveArg = True,
    max_results: GrepMaxResultsArg = None,
    session_id: ToolSessionIdArg = None,
) -> GrepSearchOutput:
    """Search code content with optional path scopes."""
    return await search_execute(
        pattern, paths, ".", regex, case_sensitive, max_results, session_id
    )
