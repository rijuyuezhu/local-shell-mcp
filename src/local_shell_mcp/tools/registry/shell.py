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
from ...schemas.input_models.shell import (
    CwdArg,
    EnterArg,
    InitialCommandArg,
    InputTextArg,
    LinesArg,
    MaxOutputBytesArg,
    PythonCodeArg,
    PythonTimeoutArg,
    RunShellTimeoutArg,
    SessionIdArg,
    ShellCommandArg,
    ShellNameArg,
)
from ...schemas.result_models.shell import (
    KillPersistentShellOutput,
    ListPersistentShellsOutput,
    ReadPersistentShellOutput,
    RunPythonCodeOutput,
    RunShellCommandOutput,
    SendPersistentShellInputOutput,
    StartPersistentShellOutput,
)
from ..contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry


class ShellToolRegistry(DeclarativeToolRegistry):
    """Register shell execution and session tools."""

    name = "shell"


local_tool = ShellToolRegistry.get_tool_decorator()


def _run_shell_command_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Run one bounded, non-interactive shell command in the controlled workspace/container. Use for build, test, package-manager, git, and inspection commands that should finish promptly. Current public timeout default/cap: {settings.run_shell_default_timeout_s}/{settings.run_shell_max_timeout_s} seconds. Current combined output cap: {settings.max_output_bytes} bytes. For long-running, interactive, or streaming processes, use the persistent shell tools."""


def _run_python_code_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Write Python code to a temporary file and execute it in the controlled workspace/container. Use for short scripts, structured file analysis, JSON manipulation, or calculations that are easier and safer in Python than shell. Current timeout cap: {settings.run_shell_max_timeout_s} seconds. Current combined output cap: {settings.max_output_bytes} bytes. Keep code non-interactive and write durable outputs explicitly if needed."""


@local_tool(
    http_method="POST",
    http_path="/tools/run_shell_command",
    description=_run_shell_command_description,
)
async def run_shell_command(
    command: ShellCommandArg,
    cwd: CwdArg = ".",
    timeout_s: RunShellTimeoutArg = None,
    max_output_bytes: MaxOutputBytesArg = None,
) -> RunShellCommandOutput:
    """Run one non-interactive shell command."""
    return RunShellCommandOutput.model_validate(
        (
            await run_shell_command_execute(
                command, cwd, timeout_s, max_output_bytes
            )
        ).model_dump()
    )


@local_tool(
    http_method="POST",
    http_path="/tools/run_python_code",
    description=_run_python_code_description,
)
async def run_python_code(
    code: PythonCodeArg, cwd: CwdArg = ".", timeout_s: PythonTimeoutArg = 60
) -> RunPythonCodeOutput:
    """Write Python code to a temporary file and execute it."""
    return RunPythonCodeOutput.model_validate(
        await run_python_code_execute(code, cwd, timeout_s)
    )


@local_tool(http_method="POST", http_path="/tools/start_persistent_shell")
async def start_persistent_shell(
    cwd: CwdArg = ".",
    name: ShellNameArg = None,
    command: InitialCommandArg = None,
) -> StartPersistentShellOutput:
    """Start a persistent tmux-backed shell session. Use for interactive programs, development servers, REPLs, long-running watches, or commands whose output must be read incrementally. Parameters: cwd defaults to '.' and is resolved relative to the workspace unless an allowed absolute path is supplied; name is an optional human-readable session label; command is optional and starts immediately in the session. For one-shot commands, use run_shell_command."""
    return StartPersistentShellOutput.model_validate(
        await start_persistent_shell_execute(cwd, name, command)
    )


@local_tool(http_method="POST", http_path="/tools/send_persistent_shell_input")
async def send_persistent_shell_input(
    session_id: SessionIdArg, input_text: InputTextArg, enter: EnterArg = True
) -> SendPersistentShellInputOutput:
    """Send input to an existing persistent shell session. Use after start_persistent_shell when a process is waiting for commands or interactive input. Set enter=false only when intentionally sending partial input without a newline."""
    return SendPersistentShellInputOutput.model_validate(
        await send_persistent_shell_input_execute(session_id, input_text, enter)
    )


@local_tool(http_method="POST", http_path="/tools/read_persistent_shell_output")
async def read_persistent_shell_output(
    session_id: SessionIdArg, lines: LinesArg = 200
) -> ReadPersistentShellOutput:
    """Read recent output from a persistent shell session. Use after start_persistent_shell or send_persistent_shell_input to inspect incremental output without blocking. Parameters: session_id must be an id returned by start_persistent_shell or list_persistent_shells; lines defaults to 200 and controls how many recent lines are returned. Increase lines only when needed for context."""
    return ReadPersistentShellOutput.model_validate(
        await read_persistent_shell_output_execute(session_id, lines)
    )


@local_tool(http_method="POST", http_path="/tools/kill_persistent_shell")
async def kill_persistent_shell(
    session_id: SessionIdArg,
) -> KillPersistentShellOutput:
    """Terminate a persistent shell session by session_id. Use when a server, watch process, REPL, or stuck command is no longer needed. This is destructive for that session but does not delete files."""
    return KillPersistentShellOutput.model_validate(
        await kill_persistent_shell_execute(session_id)
    )


@local_tool(http_method="GET", http_path="/tools/list_persistent_shells")
async def list_persistent_shells() -> ListPersistentShellsOutput:
    """List active persistent shell sessions. Use before reading, sending to, or killing sessions when you do not know the session_id or need to check what long-running processes are active."""
    return ListPersistentShellsOutput.model_validate(
        await list_persistent_shells_execute()
    )
