"""Typed input annotations for the bash tool."""

from typing import Annotated

from pydantic import Field

BashCommandArg = Annotated[
    str,
    Field(
        description="Shell command string to execute for terminal work such as tests, builds, package managers, git, or scripts."
    ),
]
BashCwdArg = Annotated[
    str,
    Field(
        description="Working directory for the command; prefer this over embedding directory changes in the command."
    ),
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
        description="Optional environment variables for multiline or quote-heavy values; reference them from the command."
    ),
]
BashAsyncArg = Annotated[
    bool,
    Field(
        description="Whether to start long-running non-interactive work as a tracked background job."
    ),
]
BashPtyArg = Annotated[
    bool,
    Field(
        description="Whether to start the command in a persistent PTY shell session for interactive programs, REPLs, servers, or commands needing later input."
    ),
]
BashNameArg = Annotated[
    str | None,
    Field(
        description="Optional name for the tracked job or persistent shell session."
    ),
]
