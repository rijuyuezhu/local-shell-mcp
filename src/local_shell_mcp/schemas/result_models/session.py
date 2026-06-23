"""Typed structured outputs for explicit agent sessions."""

from typing import Literal

from pydantic import BaseModel, Field


class GitSessionInfo(BaseModel):
    """Lightweight git orientation for a session workdir."""

    is_repo: bool = Field(
        description="Whether the session workdir is inside a git repository."
    )
    root: str | None = Field(
        default=None, description="Git repository root, if available."
    )
    branch: str | None = Field(
        default=None,
        description="Current branch or short commit name, if available.",
    )
    dirty: bool | None = Field(
        default=None,
        description="Whether git reports uncommitted changes, if available.",
    )


class SessionStartOutput(BaseModel):
    """Explicit agent/workspace session orientation."""

    session_id: str = Field(
        description="8-character alphanumeric agent/workspace session id."
    )
    target: Literal["local", "remote"] = Field(
        description="Execution target bound to this session."
    )
    workdir: str = Field(description="Canonical workdir bound to this session.")
    machine: str | None = Field(
        default=None, description="Remote worker name for remote sessions."
    )
    created_at: float = Field(
        description="Unix timestamp when the session was created."
    )
    updated_at: float = Field(
        description="Unix timestamp when the session was last touched."
    )
    expires_at: float | None = Field(
        default=None,
        description="Optional Unix timestamp when the session expires.",
    )
    label: str | None = Field(
        default=None, description="Optional human-readable session label."
    )
    workspace_root: str = Field(
        description="Configured local workspace root for this server."
    )
    git: GitSessionInfo = Field(
        description="Lightweight git orientation for the session workdir."
    )
    instruction_files: list[str] = Field(
        description="Workspace-relative project instruction files discovered near the session workdir."
    )
    message: str = Field(
        description="Short model-facing instruction for using this session."
    )
