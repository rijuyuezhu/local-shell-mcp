"""High-level read tool registry."""

import asyncio

from ...ops.read import read_execute
from ...schemas.input_models.files import ToolSessionIdArg
from ...schemas.input_models.read import ReadPathArg
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
    return f"""Read files or list directories with optional selector suffixes in the path. Use this for normal code context. Put ranges in the path selector and keep numbered output for edit grounding. File output includes snapshot metadata for edit_lines. Supported selectors: path:50, path:50-80, path:50+20, path:raw, and path:50-80:raw. Current per-file read cap: {settings.max_file_read_bytes} bytes."""


@read_tool(
    http_method="POST",
    http_path="/tools/read",
    description=_read_description,
    mcp_scopes=("shell:read",),
)
async def read(
    path: ReadPathArg,
    session_id: ToolSessionIdArg = None,
) -> ReadOutput:
    """Read a file or directory with optional path selector suffixes."""
    return await asyncio.to_thread(read_execute, path, session_id)
