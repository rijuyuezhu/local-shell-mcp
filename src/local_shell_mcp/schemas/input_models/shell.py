"""Typed input annotations for shell-facing tools."""

from typing import Annotated

from pydantic import Field

ShellCommandArg = Annotated[
    str,
    Field(
        description="Shell command string executed with the configured shell."
    ),
]
CwdArg = Annotated[
    str,
    Field(
        description="Working directory for the operation. Relative paths resolve inside the configured workspace."
    ),
]
RunShellTimeoutArg = Annotated[
    int | None,
    Field(
        description="Optional public tool timeout in seconds. Omit to use the configured default; values above the configured public cap are rejected."
    ),
]
MaxOutputBytesArg = Annotated[
    int | None,
    Field(
        description="Optional combined stdout/stderr byte budget. Values above the configured server cap are clamped."
    ),
]
PythonCodeArg = Annotated[
    str,
    Field(
        description="Complete Python source code to write to a temporary script and execute."
    ),
]
PythonTimeoutArg = Annotated[
    int,
    Field(
        description="Python script timeout in seconds, bounded by the public shell timeout cap."
    ),
]
SessionIdArg = Annotated[
    str,
    Field(
        description="Persistent shell session_id returned by bash(pty=true) or list_persistent_shells."
    ),
]
InputTextArg = Annotated[
    str, Field(description="Text to send to the persistent shell session.")
]
EnterArg = Annotated[
    bool, Field(description="Whether to send Enter after the input text.")
]
ShellNameArg = Annotated[
    str | None,
    Field(
        description="Optional human-readable session label used to derive the tmux session name."
    ),
]
InitialCommandArg = Annotated[
    str | None,
    Field(
        description="Optional command to start immediately in the persistent shell. Omit to start the configured shell executable."
    ),
]
LinesArg = Annotated[
    int,
    Field(
        description="Number of recent terminal lines to capture from the persistent shell."
    ),
]

ToolPurposeArg = Annotated[
    str | None,
    Field(
        default=None,
        description="Optional short purpose explaining why this tool call is being made. Maximum 500 characters.",
    ),
]
ToolExplanationArg = Annotated[
    str | None,
    Field(
        default=None,
        description="Optional longer explanation for the tool call. Maximum 2000 characters.",
    ),
]
