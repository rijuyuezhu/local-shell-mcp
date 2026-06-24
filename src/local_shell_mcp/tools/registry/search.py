"""Search and tree-view tool registry."""

from ...ops.search import (
    glob_search_execute,
    search_execute,
    tree_view_execute,
)
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
from ...schemas.input_models.session import SessionIdArg
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
    return f"""Return a compact directory tree inside an explicit agent/workspace session for high-level project orientation before targeted file reads. Use tree_view when you need structure, directories, and broad layout; use glob_search when you already know filename patterns; use search when you need content matches. Pass the session_id returned by session_start. cwd defaults to the session workdir; any relative cwd override resolves inside that session workdir. Remote sessions dispatch to the paired worker session. Current max tree entries: {settings.max_tree_entries}."""


def _glob_search_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Find files by glob pattern inside an explicit agent/workspace session when you know filename patterns and need matching paths, not file contents. Use glob_search for path discovery by pattern; use tree_view for directory shape; use search for content matches with edit-grounding metadata. Pass the session_id returned by session_start. cwd defaults to the session workdir; any relative cwd override resolves inside that session workdir. Remote sessions dispatch to the paired worker session. Current max glob results: {settings.max_glob_results}."""


def _search_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Search code content inside an explicit agent/workspace session for matching lines. Use this built-in search for content discovery instead of shell grep/ripgrep when you need editable results, because matches carry hashline grounding for hashline_edit. Use read when you already know the exact file/range, glob_search when you only need matching paths, and workspace_search/fetch only for connector-style sessionless document retrieval. pattern is text or regex depending on regex; paths scopes to files, directories, or globs. Results include `[path#snapshot_id]` plus `line:text` rows, grouped context, snapshot metadata, and displayed ranges that can be copied into hashline_edit. Use edit_lines only when you already have exact structured path/start/end/replacement data. Current max_grep_results={settings.max_grep_results}."""


@local_tool(
    http_method="POST",
    http_path="/tools/tree",
    description=_tree_view_description,
    mcp_scopes=("shell:read",),
)
async def tree_view(
    session_id: SessionIdArg,
    cwd: TreeCwdArg = ".",
    depth: TreeDepthArg = 3,
    max_entries: TreeMaxEntriesArg = 500,
) -> TreeViewOutput:
    """Return a compact directory tree rooted at cwd inside a session."""
    return await tree_view_execute(session_id, cwd, depth, max_entries)


@local_tool(
    http_method="POST",
    http_path="/tools/glob",
    description=_glob_search_description,
    mcp_scopes=("shell:read",),
)
async def glob_search(
    session_id: SessionIdArg,
    pattern: GlobPatternArg,
    cwd: SearchCwdArg = ".",
    max_results: GlobMaxResultsArg = 500,
) -> GlobSearchOutput:
    """Find files by glob pattern inside a session."""
    return await glob_search_execute(session_id, pattern, cwd, max_results)


@local_tool(
    http_method="POST",
    http_path="/tools/search",
    description=_search_description,
    annotations="read_only",
    mcp_scopes=("shell:read",),
)
async def search(
    session_id: SessionIdArg,
    pattern: GrepQueryArg,
    paths: SearchPathsArg = None,
    regex: RegexArg = True,
    case_sensitive: CaseSensitiveArg = True,
    max_results: GrepMaxResultsArg = None,
) -> GrepSearchOutput:
    """Search code content with optional path scopes."""
    return await search_execute(
        pattern, paths, ".", regex, case_sensitive, max_results, session_id
    )
