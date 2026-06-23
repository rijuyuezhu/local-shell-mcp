"""Typed structured outputs for the bash tool."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class BashOutput(BaseModel):
    """Result returned by the bash tool."""

    mode: Literal["command", "job", "pty"] = Field(
        description="Execution mode selected by the bash tool."
    )
    command: str = Field(description="Shell command submitted by the caller.")
    cwd: str = Field(description="Working directory requested by the caller.")
    result: dict[str, Any] = Field(
        description="Structured result from bounded command, async job, or PTY mode selected by bash."
    )
