"""Response models for shell command execution."""

from pydantic import BaseModel, Field


class CommandResult(BaseModel):
    """Completed subprocess result."""

    ok: bool = Field(
        description="Whether the subprocess exited with code 0 before timeout."
    )
    exit_code: int | None = Field(
        description="Process exit code, or null when no process exited."
    )
    timed_out: bool = Field(
        default=False,
        description="Whether execution was terminated after exceeding its timeout.",
    )
    duration_ms: int = Field(
        description="Elapsed command runtime in milliseconds."
    )
    cwd: str = Field(
        description="Working directory used to run the command, displayed relative to the workspace when possible."
    )
    command: str = Field(description="Shell command string that was executed.")
    stdout: str = Field(
        default="",
        description="Captured standard output after byte-limit truncation.",
    )
    stderr: str = Field(
        default="",
        description="Captured standard error after byte-limit truncation.",
    )
    truncated: bool = Field(
        default=False,
        description="Whether stdout or stderr was truncated to fit output limits.",
    )
