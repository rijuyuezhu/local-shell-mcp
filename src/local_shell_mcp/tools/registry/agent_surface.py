"""Agent-oriented high-level tool registry."""

import asyncio

from ...ops.agent_surface import read_execute
from ...schemas.input_models.agent_surface import AgentReadPathArg
from ...schemas.input_models.files import ToolSessionIdArg
from ...schemas.result_models.agent_surface import ReadOutput
from ...tools.contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry


class AgentSurfaceToolRegistry(DeclarativeToolRegistry):
    """Register high-level semantic tools designed for coding agents."""

    name = "agent_surface"
    """Registry group name used for tool-surface organization."""


agent_tool = AgentSurfaceToolRegistry.get_tool_decorator()


def _read_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Read a file or directory using an oh-my-pi-style path selector. Prefer this high-level read tool when gathering code context for edits. File output defaults to numbered_content with original line numbers plus snapshot metadata; append :raw only when exact unnumbered text is needed. Supported selectors: path:50, path:50-80, path:50+20, path:raw, and path:50-80:raw. Current per-file read cap: {settings.max_file_read_bytes} bytes."""


@agent_tool(
    http_method="POST",
    http_path="/tools/read",
    description=_read_description,
    mcp_scopes=("shell:read",),
)
async def read(
    path: AgentReadPathArg,
    session_id: ToolSessionIdArg = None,
) -> ReadOutput:
    """Read a file or directory with optional path selector suffixes."""
    return await asyncio.to_thread(read_execute, path, session_id)
