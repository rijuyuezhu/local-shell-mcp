"""Agent-oriented high-level tool registry."""

import asyncio

from ...ops.files import list_files_execute, read_file_execute
from ...schemas.input_models.agent_surface import AgentReadPathArg
from ...schemas.input_models.files import ToolSessionIdArg
from ...schemas.result_models.agent_surface import ReadOutput
from ...schemas.result_models.files import ListFilesOutput
from ...tool_session.selectors import parse_read_target
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


def _directory_content(result: ListFilesOutput) -> str:
    """Return a compact model-facing listing for a directory result."""
    lines = [f"{entry.type}\t{entry.path}" for entry in result.entries]
    if result.is_truncated:
        lines.append("[listing truncated]")
    return "\n".join(lines)


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
    target = parse_read_target(path)
    listed = None
    if not target.raw and target.start_line is None and target.end_line is None:
        try:
            listed = await asyncio.to_thread(
                list_files_execute,
                target.path,
                False,
                500,
            )
        except NotADirectoryError:
            listed = None
    if listed is not None:
        return ReadOutput(
            kind="directory",
            path=target.path,
            raw=target.raw,
            content=_directory_content(listed),
            directory=listed,
        )

    file_result = await asyncio.to_thread(
        read_file_execute,
        target.path,
        target.start_line,
        target.end_line,
        session_id,
    )
    return ReadOutput(
        kind="file",
        path=file_result.path,
        raw=target.raw,
        content=file_result.content
        if target.raw
        else file_result.numbered_content,
        file=file_result,
    )
