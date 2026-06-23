"""Explicit agent session tool registry."""

import asyncio

from ...ops.session import session_start_execute
from ...schemas.input_models.session import (
    SessionLabelArg,
    SessionMachineArg,
    SessionTargetArg,
    SessionWorkdirArg,
)
from ...schemas.result_models.session import SessionStartOutput
from ..contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry


class SessionToolRegistry(DeclarativeToolRegistry):
    """Register explicit agent session tools."""

    name = "session"
    """Registry group name used for tool-surface organization."""


session_tool = SessionToolRegistry.get_tool_decorator()


def _session_start_description(_context: McpToolContext) -> str:
    return """Start an explicit agent/workspace session and bind it to a workdir. Call this before substantial workspace work, then pass the returned 8-character session_id to read, search, edit_lines, bash, job, and other session-bound tools. Local sessions are supported now; remote sessions will create a paired worker session in a later slice."""


@session_tool(
    http_method="POST",
    http_path="/tools/session_start",
    description=_session_start_description,
    mcp_scopes=("shell:read",),
)
async def session_start(
    target: SessionTargetArg = "local",
    workdir: SessionWorkdirArg = ".",
    machine: SessionMachineArg = None,
    label: SessionLabelArg = None,
) -> SessionStartOutput:
    """Start an explicit agent/workspace session."""
    return await asyncio.to_thread(
        session_start_execute, target, workdir, machine, label
    )
