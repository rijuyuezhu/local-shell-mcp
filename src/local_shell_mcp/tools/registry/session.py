"""Explicit agent session tool registry."""

import asyncio

from ...ops.session import (
    session_change_cwd_execute,
    session_copy_execute,
    session_start_execute,
)
from ...schemas.input_models.session import (
    SessionCopyChunkSizeArg,
    SessionCopyKindArg,
    SessionCopyOverwriteArg,
    SessionCopyPathArg,
    SessionIdArg,
    SessionLabelArg,
    SessionMachineArg,
    SessionTargetArg,
    SessionWorkdirArg,
)
from ...schemas.result_models.session import (
    SessionCopyOutput,
    SessionStartOutput,
)
from ..contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry


class SessionToolRegistry(DeclarativeToolRegistry):
    """Register explicit agent session tools."""

    name = "session"
    """Registry group name used for tool-surface organization."""


session_tool = SessionToolRegistry.get_tool_decorator()


def _session_start_description(_context: McpToolContext) -> str:
    return """Start an explicit agent/workspace session and bind it to a required workdir. Use target="local" for the control-server workspace, or target="remote" with machine set to an online remote worker name and workdir set to the worker-side directory. Before calling, ask the user which project directory or remote worker to use when unclear; otherwise infer the most specific safe workdir from the task, repository, or paths the user mentioned. For local sessions, the response includes discovered instruction file paths; read relevant AGENTS.md/CLAUDE.md/config files before editing. Pass the returned 8-character session_id to read, search, hashline_edit, edit_lines, bash, job, and other session-bound tools; remote sessions dispatch those normal tools to their paired worker session."""


def _session_change_cwd_description(_context: McpToolContext) -> str:
    return """Change an existing local agent/workspace session to a new required workdir, clear stale grounding snapshots for that session, and return refreshed orientation metadata including instruction file paths. Use this when the user redirects you to a different project/subdirectory or you infer the original workdir was wrong; then read any relevant AGENTS.md/CLAUDE.md/config files before continuing edits."""


def _session_copy_description(_context: McpToolContext) -> str:
    return """Copy one file or directory between two explicit agent/workspace sessions. Source and destination may be any pair of local or remote sessions; paths resolve inside their respective session workdirs. Use this when moving artifacts across sessions instead of exposing raw transfer primitives or legacy remote pull/push tools. The response includes the selected route and whether the sessions share a target, session id, or remote machine."""


@session_tool(
    http_method="POST",
    http_path="/tools/session_start",
    description=_session_start_description,
    oauth_scopes=("shell:read",),
)
async def session_start(
    workdir: SessionWorkdirArg,
    target: SessionTargetArg = "local",
    machine: SessionMachineArg = None,
    label: SessionLabelArg = None,
) -> SessionStartOutput:
    """Start an explicit agent/workspace session."""
    return await session_start_execute(workdir, target, machine, label)


@session_tool(
    http_method="POST",
    http_path="/tools/session_change_cwd",
    description=_session_change_cwd_description,
    oauth_scopes=("shell:read",),
)
async def session_change_cwd(
    session_id: SessionIdArg,
    workdir: SessionWorkdirArg,
) -> SessionStartOutput:
    """Change an explicit agent/workspace session workdir."""
    return await asyncio.to_thread(
        session_change_cwd_execute, session_id, workdir
    )


@session_tool(
    http_method="POST",
    http_path="/tools/session_copy",
    description=_session_copy_description,
    oauth_scopes=("shell:read", "shell:write"),
)
async def session_copy(
    src_session_id: SessionIdArg,
    src_path: SessionCopyPathArg,
    dst_session_id: SessionIdArg,
    dst_path: SessionCopyPathArg,
    kind: SessionCopyKindArg = "auto",
    overwrite: SessionCopyOverwriteArg = True,
    chunk_size: SessionCopyChunkSizeArg = None,
) -> SessionCopyOutput:
    """Copy a file or directory between two explicit sessions."""
    return await session_copy_execute(
        src_session_id,
        src_path,
        dst_session_id,
        dst_path,
        kind,
        overwrite,
        chunk_size,
    )
