"""Typed structured outputs for shell-facing tools."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CommandResult(BaseModel):
    """Completed subprocess result."""

    ok: bool = Field(
        description="Whether the subprocess exited with code 0 before timeout."
    )
    exit_code: int | None = Field(
        description="Process exit code, or null when no process exited."
    )
    timed_out: bool = Field(
        default=False,
        description="Whether execution was terminated after exceeding its timeout.",
    )
    duration_ms: int = Field(
        description="Elapsed command runtime in milliseconds."
    )
    cwd: str = Field(
        description="Working directory used to run the command, displayed relative to the workspace when possible."
    )
    command: str = Field(description="Shell command string that was executed.")
    stdout: str = Field(
        default="",
        description="Captured standard output after byte-limit truncation.",
    )
    stderr: str = Field(
        default="",
        description="Captured standard error after byte-limit truncation.",
    )
    truncated: bool = Field(
        default=False,
        description="Whether stdout or stderr was truncated to fit output limits.",
    )


class RunShellCommandOutput(CommandResult):
    """Result of running one bounded non-interactive shell command."""


class RunPythonCodeOutput(CommandResult):
    """Result of writing Python code to a temporary file and executing it."""

    script_path: str = Field(
        description="Workspace-relative path to the temporary Python script that was executed."
    )


class StartPersistentShellOutput(BaseModel):
    """Result of starting a tmux-backed persistent shell session."""

    model_config = ConfigDict(extra="allow")

    session_id: str = Field(
        description="Identifier used by later persistent-shell tools to send input, read output, or kill the session."
    )
    name: str | None = Field(
        default=None,
        description="Optional human-readable session label, when available.",
    )
    cwd: str | None = Field(
        default=None,
        description="Working directory where the persistent shell was started.",
    )
    command: str | None = Field(
        default=None,
        description="Initial command launched in the persistent shell, or the configured shell executable when omitted.",
    )


class SendPersistentShellInputOutput(BaseModel):
    """Result of sending input to a persistent shell session."""

    session_id: str = Field(
        description="Persistent shell session that received input."
    )
    sent_bytes: int = Field(
        description="Number of UTF-8 bytes sent to the persistent shell."
    )
    enter: bool = Field(
        description="Whether an Enter key was sent after the input text."
    )


class ReadPersistentShellOutput(BaseModel):
    """Recent output captured from a persistent shell session."""

    model_config = ConfigDict(extra="allow")

    session_id: str = Field(
        description="Persistent shell session that was read."
    )
    output: str = Field(
        default="",
        description="Captured recent terminal output from the session.",
    )
    lines: int | None = Field(
        default=None,
        description="Requested number of recent terminal lines, when returned by the implementation.",
    )


class KillPersistentShellOutput(BaseModel):
    """Result of terminating a persistent shell session."""

    model_config = ConfigDict(extra="allow")

    session_id: str = Field(
        description="Persistent shell session targeted for termination."
    )
    killed: bool | None = Field(
        default=None,
        description="Whether tmux reported that the session was killed successfully.",
    )
    stderr: str | None = Field(
        default=None,
        description="Captured tmux stderr from the kill operation, when available.",
    )


class PersistentShellInfo(BaseModel):
    """One persistent shell session entry."""

    model_config = ConfigDict(extra="allow")

    session_id: str = Field(description="Persistent shell session identifier.")
    name: str | None = Field(
        default=None, description="Optional human-readable session label."
    )
    cwd: str | None = Field(
        default=None,
        description="Current or initial working directory, when known.",
    )
    command: str | None = Field(
        default=None, description="Initial or current command, when known."
    )


class ListPersistentShellsOutput(BaseModel):
    """Active tmux-backed persistent shell sessions."""

    model_config = ConfigDict(extra="allow")

    sessions: list[dict[str, Any]] = Field(
        description="Active persistent shell sessions with at least session_id and optional implementation-specific metadata."
    )
