"""High-level read tool registry."""

from ...ops.read import read_execute
from ...schemas.input_models.read import ReadPathArg
from ...schemas.input_models.session import SessionIdArg
from ...schemas.result_models.read import ReadOutput
from ...tools.contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry


class ReadToolRegistry(DeclarativeToolRegistry):
    """Register the read tool with selector support."""

    name = "read"
    """Registry group name used for tool-surface organization."""


read_tool = ReadToolRegistry.get_tool_decorator()


def _read_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Read files or list directories inside an explicit agent/workspace session with optional selector suffixes in the path. Use this for normal code context when you know the path, especially before hashline_edit or edit_lines. Use search for content discovery across files, tree_view/list_files/glob_search for path discovery, and connector fetch only when consuming an id from workspace_search. Put ranges in the path selector and keep hashline output for edit grounding: `[path#snapshot_id]` plus `line:text` rows can be copied directly into hashline_edit, while the same snapshot metadata can ground edit_lines when you already have structured path/start/end/replacement data. Supported selectors: path:50, path:50-80, path:50+20, path:raw, and path:50-80:raw. Current per-file read cap: {settings.max_file_read_bytes} bytes."""


@read_tool(
    http_method="POST",
    http_path="/tools/read",
    description=_read_description,
    mcp_scopes=("shell:read",),
)
async def read(
    session_id: SessionIdArg,
    path: ReadPathArg,
) -> ReadOutput:
    """Read a file or directory with optional path selector suffixes."""
    return await read_execute(path, session_id)
