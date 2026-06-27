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


SessionCopyPathArg = Annotated[
    str,
    Field(
        description="Path to copy, resolved inside the corresponding source or destination session workdir."
    ),
]
SessionCopyKindArg = Annotated[
    Literal["auto", "file", "dir"],
    Field(
        description="What to copy. Use auto to infer file or directory from the source path."
    ),
]
SessionCopyOverwriteArg = Annotated[
    bool,
    Field(description="Whether an existing destination may be replaced."),
]
SessionCopyChunkSizeArg = Annotated[
    int | None,
    Field(
        description="Optional chunk size in bytes for binary transfer. Omit to use the server default."
    ),
]
OptionalSessionIdArg = Annotated[
    str | None,
    Field(
        min_length=8,
        max_length=8,
        pattern=r"^[A-Za-z0-9]{8}$",
        description="Optional explicit agent/workspace session_id used by internal transfer primitives.",
    ),
]
