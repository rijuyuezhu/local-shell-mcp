"""Typed structured outputs for the high-level bash facade."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class BashOutput(BaseModel):
    """Result returned by the high-level bash facade."""

    mode: Literal["command", "job", "pty"] = Field(
        description="Execution mode selected by the facade."
    )
    command: str = Field(description="Shell command submitted by the caller.")
    cwd: str = Field(description="Working directory requested by the caller.")
    result: dict[str, Any] = Field(
        description="Structured result from run_shell_command, job_start, or start_persistent_shell."
    )
