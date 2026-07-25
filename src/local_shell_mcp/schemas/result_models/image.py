"""Structured metadata returned with native MCP image content."""

from typing import Literal

from pydantic import BaseModel, Field


class ViewImageOutput(BaseModel):
    """Metadata accompanying one native MCP image result."""

    session_id: str = Field(description="Control-server agent session id.")
    target: Literal["local", "remote"] = Field(
        description="Whether the image came from the control workspace or a remote worker."
    )
    machine: str | None = Field(
        default=None,
        description="Remote worker name when target is remote.",
    )
    path: str = Field(
        description="Resolved display path inside the session workdir."
    )
    mime_type: str = Field(
        description="Detected image MIME type from file magic."
    )
    bytes: int = Field(description="Original image byte count.")
