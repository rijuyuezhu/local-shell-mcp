"""Shell MCP tool registry."""

from ...ops.command_ops import run_shell_command_execute
from ...ops.python_ops import run_python_code_execute
from ...ops.tmux_ops import (
    kill_persistent_shell_execute,
    list_persistent_shells_execute,
    read_persistent_shell_output_execute,
    send_persistent_shell_input_execute,
    start_persistent_shell_execute,
)
from ..contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry


class ShellToolRegistry(DeclarativeToolRegistry):
    """Register shell execution and session tools."""

    name = "shell"


local_tool = ShellToolRegistry.get_tool_decorator()


def _run_shell_command_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Run one non-interactive shell command in the controlled workspace/container. Use for build, test, package-manager, git, and inspection commands that should finish promptly. Parameters: command is the shell command string; cwd defaults to '.' and is resolved relative to the workspace unless an allowed absolute path is supplied. Timeouts: timeout_s is optional, defaults to {settings.run_shell_default_timeout_s}, and must be 1..{settings.run_shell_max_timeout_s}. Output: max_output_bytes is optional and is capped by max_output_bytes={settings.max_output_bytes}. For long-running, interactive, or streaming processes, use start_persistent_shell with send_persistent_shell_input and read_persistent_shell_output."""


def _run_python_code_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Write Python code to a temporary file and execute it in the controlled workspace/container. Use for short scripts, structured file analysis, JSON manipulation, or calculations that are easier and safer in Python than shell. Parameters: code is the full Python source to run; cwd defaults to '.' and is workspace-relative unless an allowed absolute path is supplied. Timeouts: timeout_s is in seconds, defaults to {settings.run_shell_max_timeout_s}, and should stay within the run_shell cap of {settings.run_shell_max_timeout_s} seconds. Output is capped by max_output_bytes={settings.max_output_bytes}. Keep code non-interactive and write durable outputs explicitly if needed."""


@local_tool(
    http_method="POST",
    http_path="/tools/run_shell_command",
    description=_run_shell_command_description,
)
async def run_shell_command(
    command: str,
    cwd: str = ".",
    timeout_s: int | None = None,
    max_output_bytes: int | None = None,
) -> dict:
    """Run one non-interactive shell command."""
    return (
        await run_shell_command_execute(
            command, cwd, timeout_s, max_output_bytes
        )
    ).model_dump()


@local_tool(
    http_method="POST",
    http_path="/tools/run_python_code",
    description=_run_python_code_description,
)
async def run_python_code(
    code: str, cwd: str = ".", timeout_s: int = 60
) -> dict:
    """Write Python code to a temporary file and execute it."""
    return await run_python_code_execute(code, cwd, timeout_s)


@local_tool(http_method="POST", http_path="/tools/start_persistent_shell")
async def start_persistent_shell(
    cwd: str = ".", name: str | None = None, command: str | None = None
) -> dict:
    """Start a persistent tmux-backed shell session. Use for interactive programs, development servers, REPLs, long-running watches, or commands whose output must be read incrementally. Parameters: cwd defaults to '.' and is resolved relative to the workspace unless an allowed absolute path is supplied; name is an optional human-readable session label; command is optional and starts immediately in the session. For one-shot commands, use run_shell_command."""
    return await start_persistent_shell_execute(cwd, name, command)


@local_tool(http_method="POST", http_path="/tools/send_persistent_shell_input")
async def send_persistent_shell_input(
    session_id: str, input_text: str, enter: bool = True
) -> dict:
    """Send input to an existing persistent shell session. Use after start_persistent_shell when a process is waiting for commands or interactive input. Set enter=false only when intentionally sending partial input without a newline."""
    return await send_persistent_shell_input_execute(
        session_id, input_text, enter
    )


@local_tool(http_method="POST", http_path="/tools/read_persistent_shell_output")
async def read_persistent_shell_output(
    session_id: str, lines: int = 200
) -> dict:
    """Read recent output from a persistent shell session. Use after start_persistent_shell or send_persistent_shell_input to inspect incremental output without blocking. Parameters: session_id must be an id returned by start_persistent_shell or list_persistent_shells; lines defaults to 200 and controls how many recent lines are returned. Increase lines only when needed for context."""
    return await read_persistent_shell_output_execute(session_id, lines)


@local_tool(http_method="POST", http_path="/tools/kill_persistent_shell")
async def kill_persistent_shell(session_id: str) -> dict:
    """Terminate a persistent shell session by session_id. Use when a server, watch process, REPL, or stuck command is no longer needed. This is destructive for that session but does not delete files."""
    return await kill_persistent_shell_execute(session_id)


@local_tool(http_method="GET", http_path="/tools/list_persistent_shells")
async def list_persistent_shells() -> dict:
    """List active persistent shell sessions. Use before reading, sending to, or killing sessions when you do not know the session_id or need to check what long-running processes are active."""
    return await list_persistent_shells_execute()
