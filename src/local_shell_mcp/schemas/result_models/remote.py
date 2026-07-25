"""Typed structured outputs for remote-worker tools."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RemoteInviteOutput(BaseModel):
    """One-time remote-worker enrollment invite."""

    code: str = Field(
        description="One-time enrollment code for a remote worker."
    )
    name: str | None = Field(
        default=None,
        description="Optional friendly name requested for the worker.",
    )
    workdir: str | None = Field(
        default=None,
        description="Optional starting directory requested for the worker.",
    )
    expires_at: float = Field(
        description="Unix timestamp when the invite expires."
    )
    ttl_s: int = Field(description="Invite lifetime in seconds.")
    join_url: str = Field(
        description="Control-server URL used by the worker to join."
    )
    command: str = Field(
        description="Shell command that starts the remote worker."
    )


class RemoteMachineInfo(BaseModel):
    """One registered remote worker machine."""

    name: str = Field(description="Stable remote worker name.")
    status: str = Field(description="Current worker connection status.")
    workdir: str | None = Field(
        default=None, description="Worker-side working directory, when known."
    )
    last_seen: float = Field(
        description="Unix timestamp of the last worker heartbeat."
    )
    last_seen_age_s: float | None = Field(
        default=None,
        description="Seconds elapsed since the last worker heartbeat, when known.",
    )
    offline_after_s: float | None = Field(
        default=None,
        description="Heartbeat age in seconds after which this worker is treated as offline.",
    )
    queue_depth: int | None = Field(
        default=None,
        description="Number of queued jobs waiting for this worker.",
    )
    capabilities: list[str] = Field(
        description="Tool capabilities advertised by the worker."
    )
    info: dict[str, Any] = Field(
        description="Worker environment and probe metadata."
    )


class RemoteListMachinesOutput(BaseModel):
    """Remote worker inventory."""

    machines: list[RemoteMachineInfo] = Field(
        description="Registered remote workers known to the control server."
    )
    counts: dict[str, int] = Field(
        default_factory=dict,
        description="Worker counts by status plus total.",
    )


class RemoteRevokeMachineOutput(BaseModel):
    """Remote worker revocation result."""

    machine: str = Field(
        description="Remote worker name targeted for revocation."
    )
    revoked: bool = Field(
        description="Whether the worker registration was removed."
    )


class RemoteRenameMachineOutput(BaseModel):
    """Remote worker rename result."""

    old_name: str = Field(description="Previous remote worker name.")
    new_name: str = Field(description="New remote worker name.")


class RemoteEndpoint(BaseModel):
    """Remote copy endpoint."""

    machine: str = Field(description="Remote worker name for this endpoint.")
    path: str = Field(
        description="Path on the remote worker for this endpoint."
    )


class RemoteCopyFileOutput(BaseModel):
    """Remote file copy result."""

    source: RemoteEndpoint = Field(description="Source machine and file path.")
    destination: RemoteEndpoint = Field(
        description="Destination machine and file path."
    )
    bytes: int = Field(description="Number of file bytes copied.")
    sha256: str | None = Field(
        default=None,
        description="SHA-256 digest of the copied file, when available.",
    )
    chunks: int = Field(description="Number of transfer chunks exchanged.")
    chunk_size: int = Field(
        description="Chunk size used for the file transfer."
    )


class RemoteCopyDirOutput(BaseModel):
    """Remote directory copy result."""

    source: RemoteEndpoint = Field(
        description="Source machine and directory path."
    )
    destination: RemoteEndpoint = Field(
        description="Destination machine and directory path."
    )
    archive_bytes: int = Field(
        description="Size in bytes of the transfer archive."
    )
    archive_sha256: str = Field(
        description="SHA-256 digest of the transfer archive."
    )
    chunks: int = Field(description="Number of transfer chunks exchanged.")
    entries: int = Field(
        description="Number of directory entries packed into the archive."
    )


class RemoteAdminOutput(BaseModel):
    """Remote control-plane result."""

    action: str = Field(
        description="Remote control-plane action requested by the caller."
    )
    data: dict[str, Any] = Field(
        description="Structured output returned by the control-plane action."
    )


class RemoteWorkerToolOutput(BaseModel):
    """Generic proxied remote-worker tool result."""

    model_config = ConfigDict(extra="allow")
    """Allow worker-specific output keys alongside the generic result field."""

    result: Any | None = Field(
        default=None, description="Proxied worker result payload, when present."
    )
