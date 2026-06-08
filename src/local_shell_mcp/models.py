from __future__ import annotations

from pydantic import BaseModel


class ToolResult(BaseModel):
    ok: bool = True
    message: str = ""
    data: dict | list | str | int | float | bool | None = None


class CommandResult(BaseModel):
    ok: bool
    exit_code: int | None
    timed_out: bool = False
    duration_ms: int
    cwd: str
    command: str
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False


class FileEntry(BaseModel):
    path: str
    type: str
    size: int | None = None
    modified: float | None = None


class ShellSession(BaseModel):
    session_id: str
    name: str
    cwd: str
    created_at: float
    alive: bool = True


class GrepMatch(BaseModel):
    path: str
    line: int
    column: int | None = None
    text: str
