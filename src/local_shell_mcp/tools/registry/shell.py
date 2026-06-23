"""Shell MCP tool registry."""

from ...ops.shell import (
    kill_persistent_shell_execute,
    list_persistent_shells_execute,
    read_persistent_shell_output_execute,
    run_python_code_execute,
    send_persistent_shell_input_execute,
)
from ...schemas.input_models.shell import (
    CwdArg,
    EnterArg,
    InputTextArg,
    LinesArg,
    PythonCodeArg,
    PythonTimeoutArg,
    SessionIdArg,
    ToolExplanationArg,
    ToolPurposeArg,
)
from ...schemas.result_models.shell import (
    KillPersistentShellOutput,
    ListPersistentShellsOutput,
    ReadPersistentShellOutput,
    RunPythonCodeOutput,
    SendPersistentShellInputOutput,
)
from ..contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry
from ..purpose import audit_tool_purpose


class ShellToolRegistry(DeclarativeToolRegistry):
    """Register shell execution and session tools."""

    name = "shell"
    """Registry group name used for tool-surface organization."""


local_tool = ShellToolRegistry.get_tool_decorator()


def _run_python_code_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Write Python code to a temporary file and execute it in the controlled workspace/container. Use for short scripts, structured file analysis, JSON manipulation, or calculations that are easier and safer in Python than shell. Current timeout cap: {settings.run_shell_max_timeout_s} seconds. Current combined output cap: {settings.max_output_bytes} bytes. Keep code non-interactive and write durable outputs explicitly if needed."""


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
    http_path="/tools/send_persistent_shell_input",
    mcp_scopes=("shell:read", "shell:execute"),
)
async def send_persistent_shell_input(
    session_id: SessionIdArg, input_text: InputTextArg, enter: EnterArg = True
) -> SendPersistentShellInputOutput:
    """Send input to an existing persistent shell session. Use after bash(pty=true) for interactive programs, REPLs, prompts, or manually managed shells. job_start jobs are intended to be non-interactive; use job_tail/job_stop/job_retry for those instead of sending input to their backing session. Set enter=false only when intentionally sending partial input without a newline."""
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
    """Read recent output from a persistent shell session. Use after bash(pty=true) or send_persistent_shell_input to inspect an interactive or manually managed session without blocking. For tracked non-interactive jobs, prefer job_tail because it works from job_id and refreshes job status. Parameters: session_id must be an id returned by start_persistent_shell or list_persistent_shells; lines defaults to 200 and controls how many recent lines are returned. Increase lines only when needed for context."""
    return await read_persistent_shell_output_execute(session_id, lines)


@local_tool(
    http_method="POST",
    http_path="/tools/kill_persistent_shell",
    mcp_scopes=("shell:read", "shell:execute"),
)
async def kill_persistent_shell(
    session_id: SessionIdArg,
) -> KillPersistentShellOutput:
    """Terminate a persistent shell session by session_id. Use for manually managed sessions started with bash(pty=true), such as servers, watches, REPLs, or stuck interactive commands. For tracked non-interactive jobs, prefer job_stop so the job record is updated. This is destructive for that session but does not delete files."""
    return await kill_persistent_shell_execute(session_id)


@local_tool(
    http_method="GET",
    http_path="/tools/list_persistent_shells",
    mcp_scopes=("shell:read",),
)
async def list_persistent_shells() -> ListPersistentShellsOutput:
    """List active persistent shell sessions. Use before reading, sending to, or killing sessions when you do not know the session_id or need to check what long-running processes are active."""
    return await list_persistent_shells_execute()
