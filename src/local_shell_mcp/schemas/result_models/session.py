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


class SessionCopyEndpoint(BaseModel):
    """One endpoint in a session-to-session copy."""

    session_id: str = Field(
        description="Agent/workspace session id for this endpoint."
    )
    target: Literal["local", "remote"] = Field(
        description="Execution target bound to this endpoint session."
    )
    machine: str | None = Field(
        default=None, description="Remote worker machine for remote sessions."
    )
    workdir: str = Field(
        description="Session workdir used for path resolution."
    )
    path: str = Field(
        description="Caller-provided path inside the session workdir."
    )
    resolved_path: str | None = Field(
        default=None,
        description="Resolved path reported by the underlying transfer primitive.",
    )


class SessionCopyRelation(BaseModel):
    """Relationship between the source and destination sessions."""

    route: Literal[
        "local_to_local",
        "local_to_remote",
        "remote_to_local",
        "remote_to_remote_same_machine",
        "remote_to_remote_different_machines",
    ] = Field(
        description="Transfer route selected from the two session targets."
    )
    same_session: bool = Field(
        description="Whether source and destination are the same agent session."
    )
    same_target: bool = Field(
        description="Whether source and destination have the same target type."
    )
    same_machine: bool = Field(
        description="Whether both endpoints are remote sessions on the same worker machine."
    )


class SessionCopyOutput(BaseModel):
    """Result of copying a file or directory between two sessions."""

    kind: Literal["file", "dir"] = Field(
        description="Resolved copied object kind."
    )
    source: SessionCopyEndpoint = Field(description="Source copy endpoint.")
    destination: SessionCopyEndpoint = Field(
        description="Destination copy endpoint."
    )
    relation: SessionCopyRelation = Field(
        description="Analyzed relationship between the two sessions."
    )
    bytes: int | None = Field(
        default=None, description="Number of file bytes copied for file copies."
    )
    sha256: str | None = Field(
        default=None,
        description="SHA-256 digest for file copies, when available.",
    )
    archive_bytes: int | None = Field(
        default=None, description="Transfer archive size for directory copies."
    )
    archive_sha256: str | None = Field(
        default=None,
        description="Transfer archive digest for directory copies.",
    )
    chunks: int = Field(description="Number of transfer chunks exchanged.")
    chunk_size: int = Field(description="Chunk size used for binary transfer.")
    entries: int | None = Field(
        default=None,
        description="Number of directory entries unpacked for directory copies.",
    )
