"""Typed structured outputs for the bash tool."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class BashOutput(BaseModel):
    """Result returned by the bash tool."""

    mode: Literal["command", "job", "pty"] = Field(
        description="Execution mode selected by the bash tool."
    )
    command: str = Field(description="Shell command submitted by the caller.")
    cwd: str = Field(
        description="Resolved working directory used for this bash call."
    )
    result: dict[str, Any] = Field(
        description="Structured result from bounded command, async job, or PTY mode selected by bash. Async job results include the owning agent session_id and job_id."
    )
