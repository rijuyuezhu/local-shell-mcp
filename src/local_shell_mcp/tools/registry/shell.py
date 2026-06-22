"""Shell MCP tool registry."""

from ...ops.shell import (
    kill_persistent_shell_execute,
    list_persistent_shells_execute,
    read_persistent_shell_output_execute,
    run_python_code_execute,
    run_shell_command_execute,
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
    ToolExplanationArg,
    ToolPurposeArg,
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
from ..purpose import audit_tool_purpose


class ShellToolRegistry(DeclarativeToolRegistry):
    """Register shell execution and session tools."""

    name = "shell"
    """Registry group name used for tool-surface organization."""


local_tool = ShellToolRegistry.get_tool_decorator()


def _run_shell_command_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Run one bounded, non-interactive shell command in the controlled workspace/container. Use for build, test, package-manager, git, and inspection commands that should finish promptly and do not need later input. Current public timeout default/cap: {settings.run_shell_default_timeout_s}/{settings.run_shell_max_timeout_s} seconds. Current combined output cap: {settings.max_output_bytes} bytes. For long-running non-interactive commands you want to list, tail, stop, or retry, use job_start. For interactive programs, REPLs, shells, or processes that need later input, use start_persistent_shell."""


def _run_python_code_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Write Python code to a temporary file and execute it in the controlled workspace/container. Use for short scripts, structured file analysis, JSON manipulation, or calculations that are easier and safer in Python than shell. Current timeout cap: {settings.run_shell_max_timeout_s} seconds. Current combined output cap: {settings.max_output_bytes} bytes. Keep code non-interactive and write durable outputs explicitly if needed."""


@local_tool(
    http_method="POST",
    http_path="/tools/run_shell_command",
    description=_run_shell_command_description,
    mcp_scopes=("shell:read", "shell:execute"),
)
async def run_shell_command(
    command: ShellCommandArg,
    cwd: CwdArg = ".",
    timeout_s: RunShellTimeoutArg = None,
    max_output_bytes: MaxOutputBytesArg = None,
    purpose: ToolPurposeArg = None,
    explanation: ToolExplanationArg = None,
) -> RunShellCommandOutput:
    """Run one non-interactive shell command."""
    audit_tool_purpose("run_shell_command", purpose, explanation)
    return await run_shell_command_execute(
        command, cwd, timeout_s, max_output_bytes
    )


@local_tool(
    http_method="POST",
    http_path="/tools/run_python_code",
    description=_run_python_code_description,
    mcp_scopes=("shell:read", "shell:execute"),
)
async def run_python_code(
    code: PythonCodeArg,
    cwd: CwdArg = ".",
    timeout_s: PythonTimeoutArg = 60,
    purpose: ToolPurposeArg = None,
    explanation: ToolExplanationArg = None,
) -> RunPythonCodeOutput:
    """Write Python code to a temporary file and execute it."""
    audit_tool_purpose("run_python_code", purpose, explanation)
    return await run_python_code_execute(code, cwd, timeout_s)


@local_tool(
    http_method="POST",
    http_path="/tools/start_persistent_shell",
    mcp_scopes=("shell:read", "shell:execute"),
)
async def start_persistent_shell(
    cwd: CwdArg = ".",
    name: ShellNameArg = None,
    command: InitialCommandArg = None,
    purpose: ToolPurposeArg = None,
    explanation: ToolExplanationArg = None,
) -> StartPersistentShellOutput:
    """Start a persistent tmux-backed shell session. Use this low-level session tool when the process is interactive, needs later send_persistent_shell_input calls, or should remain a manually managed shell/REPL/server. For long-running non-interactive commands that should be tracked by job_id, listed, tailed, stopped, or retried, prefer job_start. For short commands that should finish promptly, use run_shell_command. Parameters: cwd defaults to '.' and is resolved relative to the workspace unless an allowed absolute path is supplied; name is an optional human-readable session label; command is optional and starts immediately in the session."""
    audit_tool_purpose("start_persistent_shell", purpose, explanation)
    return await start_persistent_shell_execute(cwd, name, command)


@local_tool(
    http_method="POST",
    http_path="/tools/send_persistent_shell_input",
    mcp_scopes=("shell:read", "shell:execute"),
)
async def send_persistent_shell_input(
    session_id: SessionIdArg, input_text: InputTextArg, enter: EnterArg = True
) -> SendPersistentShellInputOutput:
    """Send input to an existing persistent shell session. Use after start_persistent_shell for interactive programs, REPLs, prompts, or manually managed shells. job_start jobs are intended to be non-interactive; use job_tail/job_stop/job_retry for those instead of sending input to their backing session. Set enter=false only when intentionally sending partial input without a newline."""
    return await send_persistent_shell_input_execute(
        session_id, input_text, enter
    )


@local_tool(
    http_method="POST",
    http_path="/tools/read_persistent_shell_output",
    mcp_scopes=("shell:read",),
)
async def read_persistent_shell_output(
    session_id: SessionIdArg, lines: LinesArg = 200
) -> ReadPersistentShellOutput:
    """Read recent output from a persistent shell session. Use after start_persistent_shell or send_persistent_shell_input to inspect an interactive or manually managed session without blocking. For tracked non-interactive jobs, prefer job_tail because it works from job_id and refreshes job status. Parameters: session_id must be an id returned by start_persistent_shell or list_persistent_shells; lines defaults to 200 and controls how many recent lines are returned. Increase lines only when needed for context."""
    return await read_persistent_shell_output_execute(session_id, lines)


@local_tool(
    http_method="POST",
    http_path="/tools/kill_persistent_shell",
    mcp_scopes=("shell:read", "shell:execute"),
)
async def kill_persistent_shell(
    session_id: SessionIdArg,
) -> KillPersistentShellOutput:
    """Terminate a persistent shell session by session_id. Use for manually managed sessions started with start_persistent_shell, such as servers, watches, REPLs, or stuck interactive commands. For tracked non-interactive jobs, prefer job_stop so the job record is updated. This is destructive for that session but does not delete files."""
    return await kill_persistent_shell_execute(session_id)


@local_tool(
    http_method="GET",
    http_path="/tools/list_persistent_shells",
    mcp_scopes=("shell:read",),
)
async def list_persistent_shells() -> ListPersistentShellsOutput:
    """List active persistent shell sessions. Use before reading, sending to, or killing sessions when you do not know the session_id or need to check what long-running processes are active."""
    return await list_persistent_shells_execute()
