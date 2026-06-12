"""Response models for shell command execution."""

from __future__ import annotations

from pydantic import BaseModel


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
