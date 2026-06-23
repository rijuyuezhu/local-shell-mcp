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
        description="Session target. Use local for this workspace or remote for an online worker."
    ),
]
SessionWorkdirArg = Annotated[
    str,
    Field(
        description="Working directory to bind to the session. Local paths resolve inside the configured workspace; remote paths resolve on the selected worker."
    ),
]
SessionMachineArg = Annotated[
    str | None,
    Field(
        description="Required remote worker machine name when target is remote. Omit for local sessions."
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
