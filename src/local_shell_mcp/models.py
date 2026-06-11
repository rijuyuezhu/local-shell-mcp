"""Define shared response shapes returned by command, filesystem, shell-session, grep, and tool handlers."""

from __future__ import annotations

from pydantic import BaseModel


class ToolResult(BaseModel):
    """Generic tool response envelope."""

    ok: bool = True
    """Whether the tool call completed successfully."""
    message: str = ""
    """Human-readable status, warning, or error detail."""
    data: dict | list | str | int | float | bool | None = None
    """Tool-specific payload returned to the caller."""


class CommandResult(BaseModel):
    """Completed subprocess result."""

    ok: bool
    """Whether the subprocess exited successfully before timeout."""
    exit_code: int | None
    """Process exit code, or None when the command did not exit."""
    timed_out: bool = False
    """Whether execution was terminated after exceeding its timeout."""
    duration_ms: int
    """Elapsed command runtime in milliseconds."""
    cwd: str
    """Working directory used to run the command."""
    command: str
    """Shell command string that was executed."""
    stdout: str = ""
    """Captured standard output after byte-limit truncation."""
    stderr: str = ""
    """Captured standard error after byte-limit truncation."""
    truncated: bool = False
    """Whether stdout or stderr was truncated to fit output limits."""


class FileEntry(BaseModel):
    """Directory listing entry with basic file metadata."""

    path: str
    """Workspace-relative display path for the entry."""
    type: str
    """Entry kind, such as file, dir, or symlink."""
    size: int | None = None
    """File size in bytes when available for this entry type."""
    modified: float | None = None
    """Last modification time as a Unix timestamp when available."""


class ShellSession(BaseModel):
    """Persistent shell session descriptor."""

    session_id: str
    """Stable identifier for the shell session."""
    name: str
    """Human-readable session name."""
    cwd: str
    """Current working directory for the session."""
    created_at: float
    """Session creation time as a Unix timestamp."""
    alive: bool = True
    """Whether the backing shell process is still running."""


class GrepMatch(BaseModel):
    """One ripgrep match."""

    path: str
    """Workspace-relative path containing the match."""
    line: int
    """One-based line number containing the match."""
    column: int | None = None
    """One-based column number of the match when reported."""
    text: str
    """Line text returned for the match."""
