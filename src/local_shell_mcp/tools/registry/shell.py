"""Shell MCP tool registry."""

from __future__ import annotations

from ...ops.command_ops import public_run_shell
from ...ops.python_ops import run_python_script
from ...ops.tmux_ops import (
    kill_shell,
    list_shells,
    read_shell,
    send_shell,
    start_shell,
)
from ..contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry


class ShellToolRegistry(DeclarativeToolRegistry):
    """Register shell execution and session tools."""

    name = "shell"


local_tool = ShellToolRegistry.get_tool_decorator()


def _run_shell_tool_description(context: McpToolContext) -> str:
    settings = context.settings
    return (
        "Run one non-interactive shell command in the controlled workspace/container. "
        "Use for build, test, package-manager, git, and inspection commands that should finish promptly. "
        "Parameters: command is the shell command string; cwd defaults to '.' and is resolved relative to the workspace "
        "unless an allowed absolute path is supplied; timeout_s is in seconds, optional, "
        f"defaults to {settings.public_run_shell_default_timeout_s} and must be 1..{settings.public_run_shell_max_timeout_s}; "
        f"max_output_bytes is optional and is capped by max_output_bytes={settings.max_output_bytes}. "
        "For long-running, interactive, or streaming processes, use shell_start with shell_send and shell_read instead."
    )


def _run_python_tool_description(context: McpToolContext) -> str:
    settings = context.settings
    return (
        "Write Python code to a temporary file and execute it in the controlled workspace/container. "
        "Use for short scripts, structured file analysis, JSON manipulation, or calculations that are easier and safer in Python than shell. "
        "Parameters: code is the full Python source to run; cwd defaults to '.' and is workspace-relative unless an allowed absolute path is supplied; "
        f"timeout_s is in seconds, defaults to 60, and should stay within the public run_shell cap of {settings.public_run_shell_max_timeout_s} seconds. "
        f"Returned output is capped by max_output_bytes={settings.max_output_bytes}. Keep code non-interactive and write durable outputs explicitly if needed."
    )


@local_tool(
    http_method="POST",
    http_path="/tools/run_shell",
    name="run_shell_tool",
    description=_run_shell_tool_description,
)
async def run_shell_tool(
    command: str,
    cwd: str = ".",
    timeout_s: int | None = None,
    max_output_bytes: int | None = None,
) -> dict:
    """Run one non-interactive shell command."""
    return (
        await public_run_shell(command, cwd, timeout_s, max_output_bytes)
    ).model_dump()


@local_tool(
    http_method="POST",
    http_path="/tools/run_python",
    name="run_python_tool",
    description=_run_python_tool_description,
)
async def run_python_tool(
    code: str, cwd: str = ".", timeout_s: int = 60
) -> dict:
    """Write Python code to a temporary file and execute it."""
    return await run_python_script(code, cwd, timeout_s)


@local_tool(http_method="POST", http_path="/tools/shell_start")
async def shell_start(
    cwd: str = ".", name: str | None = None, command: str | None = None
) -> dict:
    """Start a persistent tmux-backed shell session. Use for interactive programs, development servers, REPLs, long-running watches, or commands whose output must be read incrementally. Parameters: cwd defaults to '.' and is resolved relative to the workspace unless an allowed absolute path is supplied; name is an optional human-readable session label; command is optional and starts immediately in the session. For one-shot commands, prefer run_shell_tool."""
    return await start_shell(cwd, name, command)


@local_tool(http_method="POST", http_path="/tools/shell_send")
async def shell_send(
    session_id: str, input_text: str, enter: bool = True
) -> dict:
    """Send input to an existing persistent shell session. Use after shell_start when a process is waiting for commands or interactive input. Set enter=false only when intentionally sending partial input without a newline."""
    return await send_shell(session_id, input_text, enter)


@local_tool(http_method="POST", http_path="/tools/shell_read")
async def shell_read(session_id: str, lines: int = 200) -> dict:
    """Read recent output from a persistent shell session. Use after shell_start or shell_send to inspect incremental output without blocking. Parameters: session_id must be an id returned by shell_start or shell_list; lines defaults to 200 and controls how many recent lines are returned. Increase lines only when needed for context."""
    return await read_shell(session_id, lines)


@local_tool(http_method="POST", http_path="/tools/shell_kill")
async def shell_kill(session_id: str) -> dict:
    """Terminate a persistent shell session by session_id. Use when a server, watch process, REPL, or stuck command is no longer needed. This is destructive for that session but does not delete files."""
    return await kill_shell(session_id)


@local_tool(http_method="GET", http_path="/tools/shell_list")
async def shell_list() -> dict:
    """List active persistent shell sessions. Use before reading, sending to, or killing sessions when you do not know the session_id or need to check what long-running processes are active."""
    return await list_shells()
