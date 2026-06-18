"""Typed structured outputs for remote-worker tools."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class RemoteInviteOutput(BaseModel):
    """One-time remote-worker enrollment invite."""

    code: str
    name: str | None = None
    workdir: str | None = None
    expires_at: float
    ttl_s: int
    join_url: str
    command: str


class RemoteMachineInfo(BaseModel):
    """One registered remote worker machine."""

    name: str
    status: str
    workdir: str | None = None
    last_seen: float
    capabilities: list[str]
    info: dict[str, Any]


class RemoteListMachinesOutput(BaseModel):
    """Remote worker inventory."""

    machines: list[RemoteMachineInfo]


class RemoteRevokeMachineOutput(BaseModel):
    """Remote worker revocation result."""

    machine: str
    revoked: bool


class RemoteRenameMachineOutput(BaseModel):
    """Remote worker rename result."""

    old_name: str
    new_name: str


class RemoteEndpoint(BaseModel):
    """Remote copy endpoint."""

    machine: str
    path: str


class RemoteCopyFileOutput(BaseModel):
    """Remote file copy result."""

    source: RemoteEndpoint
    destination: RemoteEndpoint
    bytes: int
    sha256: str | None = None
    chunks: int
    chunk_size: int


class RemoteCopyDirOutput(BaseModel):
    """Remote directory copy result."""

    source: RemoteEndpoint
    destination: RemoteEndpoint
    archive_bytes: int
    archive_sha256: str
    chunks: int
    entries: int


class RemoteWorkerToolOutput(BaseModel):
    """Generic proxied remote-worker tool result."""

    model_config = ConfigDict(extra="allow")

    result: Any | None = None
