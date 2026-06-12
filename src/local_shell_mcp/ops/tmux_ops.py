"""tmux-backed persistent shell session helpers."""

from __future__ import annotations

import re
import shlex
import uuid

from ..audit import audit
from ..config.settings import get_settings
from .command_ops import check_command_policy, run_shell
from .path_ops import relative_display, resolve_path
from .shell_models import CommandResult


def _tmux_session_name(name: str | None = None) -> str:
    """Normalize user-facing shell session names into the tmux naming scheme used by the server."""
    base = name or f"mcp-{uuid.uuid4().hex[:8]}"
    return re.sub(r"[^A-Za-z0-9_.-]", "-", base)[:64]


async def tmux(args: list[str], timeout_s: int = 10) -> CommandResult:
    """Run a tmux command with a bounded timeout and normalized command result payload."""
    cmd = " ".join(shlex.quote(x) for x in [get_settings().tmux_bin, *args])
    return await run_shell(cmd, cwd=".", timeout_s=timeout_s)


async def start_shell(
    cwd: str = ".", name: str | None = None, command: str | None = None
) -> dict:
    """Start or replace a tmux-backed persistent shell session in a resolved working directory."""
    resolved_cwd = resolve_path(cwd, must_exist=True)
    sessions = await list_shells()
    max_sessions = max(1, get_settings().max_tmux_sessions)
    if len(sessions.get("sessions", [])) >= max_sessions:
        raise RuntimeError(
            f"Refusing to start more than {max_sessions} tmux sessions"
        )
    session = _tmux_session_name(name)
    initial = command or get_settings().shell_executable
    check_command_policy(initial)
    cmd = [
        "new-session",
        "-d",
        "-s",
        session,
        "-c",
        str(resolved_cwd),
        initial,
    ]
    result = await tmux(cmd)
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout)
    audit(
        "shell_start", session=session, cwd=str(resolved_cwd), command=initial
    )
    return {
        "session_id": session,
        "cwd": relative_display(resolved_cwd),
        "command": initial,
    }


async def send_shell(
    session_id: str, input_text: str, enter: bool = True
) -> dict:
    """Send input to a persistent shell session, optionally appending Enter."""
    args = ["send-keys", "-t", session_id, input_text]
    if enter:
        args.append("Enter")
    result = await tmux(args)
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout)
    audit(
        "shell_send",
        session=session_id,
        bytes=len(input_text.encode()),
        enter=enter,
    )
    return {
        "session_id": session_id,
        "sent_bytes": len(input_text.encode()),
        "enter": enter,
    }


async def read_shell(session_id: str, lines: int = 200) -> dict:
    """Read recent output from a persistent shell session through tmux capture-pane."""
    result = await tmux(
        ["capture-pane", "-p", "-t", session_id, "-S", f"-{max(1, lines)}"]
    )
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout)
    audit("shell_read", session=session_id, lines=lines)
    return {"session_id": session_id, "output": result.stdout}


async def kill_shell(session_id: str) -> dict:
    """Terminate a persistent shell session by its normalized tmux session id."""
    result = await tmux(["kill-session", "-t", session_id])
    audit("shell_kill", session=session_id, ok=result.ok)
    return {
        "session_id": session_id,
        "killed": result.ok,
        "stderr": result.stderr,
    }


async def list_shells() -> dict:
    """List active tmux-backed shell sessions managed by local-shell-mcp."""
    result = await tmux(
        [
            "list-sessions",
            "-F",
            "#{session_name}\t#{session_created}\t#{session_attached}",
        ],
        timeout_s=5,
    )
    if not result.ok:
        # tmux exits nonzero when no server/sessions exist.
        return {"sessions": []}
    sessions = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if parts:
            sessions.append(
                {
                    "session_id": parts[0],
                    "created": parts[1] if len(parts) > 1 else None,
                    "attached": parts[2] if len(parts) > 2 else None,
                }
            )
    return {"sessions": sessions}
