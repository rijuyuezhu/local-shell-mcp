"""Typed input annotations for explicit agent sessions."""

from typing import Annotated, Literal

from pydantic import Field

SessionIdArg = Annotated[
    str,
    Field(
        min_length=8,
        max_length=8,
        pattern=r"^[A-Za-z0-9]{8}$",
        description="8-character alphanumeric agent/workspace session_id returned by session_start.",
    ),
]
SessionTargetArg = Annotated[
    Literal["local", "remote"],
    Field(
        description="Session target. Use local for this workspace; remote support is added in a later slice."
    ),
]
SessionWorkdirArg = Annotated[
    str,
    Field(
        description="Working directory to bind to the session. Local paths resolve inside the configured workspace."
    ),
]
SessionMachineArg = Annotated[
    str | None,
    Field(
        description="Remote worker machine name for remote sessions. Omit for local sessions."
    ),
]
SessionLabelArg = Annotated[
    str | None,
    Field(
        min_length=1,
        max_length=80,
        description="Optional human-readable label for this agent session.",
    ),
]
