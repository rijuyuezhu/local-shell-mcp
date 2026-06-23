"""Typed input annotations for the high-level bash facade."""

from typing import Annotated

from pydantic import Field

BashCommandArg = Annotated[
    str,
    Field(description="Shell command string to execute."),
]
BashCwdArg = Annotated[
    str,
    Field(description="Working directory for the command."),
]
BashTimeoutArg = Annotated[
    int | None,
    Field(description="Optional timeout in seconds for bounded command mode."),
]
BashMaxOutputBytesArg = Annotated[
    int | None,
    Field(
        description="Optional combined stdout/stderr byte budget for bounded command mode."
    ),
]
BashEnvArg = Annotated[
    dict[str, str] | None,
    Field(
        description="Optional environment variables to prefix onto the shell command."
    ),
]
BashAsyncArg = Annotated[
    bool,
    Field(
        description="Whether to start the command as a tracked background job."
    ),
]
BashPtyArg = Annotated[
    bool,
    Field(
        description="Whether to start the command in a persistent PTY shell session."
    ),
]
BashNameArg = Annotated[
    str | None,
    Field(
        description="Optional name for the tracked job or persistent shell session."
    ),
]
