"""Shell MCP tool registry."""

from ...ops.bash import run_python_code_execute
from ...ops.shell import (
    kill_persistent_shell_execute,
    list_persistent_shells_execute,
    read_persistent_shell_output_execute,
    send_persistent_shell_input_execute,
)
from ...schemas.input_models.bash import (
    BashAsyncArg,
    BashCwdArg,
    BashEnvArg,
    BashMaxOutputBytesArg,
    BashNameArg,
    BashPtyArg,
    BashTimeoutArg,
)
from ...schemas.input_models.session import SessionIdArg
from ...schemas.input_models.shell import (
    EnterArg,
    InputTextArg,
    LinesArg,
    PythonCodeArg,
    ShellIdArg,
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
    """Register shell execution and persistent-shell companion tools."""

    name = "shell"
    """Registry group name used for tool-surface organization."""


local_tool = ShellToolRegistry.get_tool_decorator()


def _run_python_code_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Write Python code to a temporary file and execute it inside an explicit agent/workspace session. Pass the session_id returned by session_start. This is a convenience wrapper over bash that runs `python3 <temporary-script>` and supports the same cwd, timeout_s, max_output_bytes, env, async_, pty, and name controls. cwd defaults to the session workdir; any cwd override resolves inside that session workdir. Default mode is bounded and returns captured stdout/stderr under result. Set async_=true for a non-interactive background job owned by the same session_id and managed with job. Set pty=true only when the Python process needs an interactive terminal, returning shell_id for persistent-shell companion tools. Current bounded command timeout default/cap: {settings.run_shell_default_timeout_s}/{settings.run_shell_max_timeout_s} seconds."""


@local_tool(
    http_method="POST",
    http_path="/tools/run_python_code",
    description=_run_python_code_description,
    mcp_scopes=("shell:read", "shell:execute"),
)
async def run_python_code(
    session_id: SessionIdArg,
    code: PythonCodeArg,
    cwd: BashCwdArg = ".",
    timeout_s: BashTimeoutArg = None,
    max_output_bytes: BashMaxOutputBytesArg = None,
    env: BashEnvArg = None,
    async_: BashAsyncArg = False,
    pty: BashPtyArg = False,
    name: BashNameArg = None,
    purpose: ToolPurposeArg = None,
) -> RunPythonCodeOutput:
    """Write Python code to a temporary file and execute it through bash modes."""
    audit_tool_purpose("run_python_code", purpose)
    return await run_python_code_execute(
        session_id,
        code,
        cwd,
        timeout_s,
        max_output_bytes,
        env,
        async_,
        pty,
        name,
    )


@local_tool(
    http_method="POST",
    http_path="/tools/send_persistent_shell_input",
    mcp_scopes=("shell:read", "shell:execute"),
)
async def send_persistent_shell_input(
    shell_id: ShellIdArg, input_text: InputTextArg, enter: EnterArg = True
) -> SendPersistentShellInputOutput:
    """Send input to an existing persistent shell created by bash(pty=true). Pass shell_id returned by bash PTY mode or list_persistent_shells; shell_id is separate from the agent/workspace session_id. Use this for interactive programs, REPLs, prompts, and manually managed server shells that need later input. Jobs started with bash(async_=true) are non-interactive background jobs; use the job companion for those instead. Set enter=false only when intentionally sending partial input without a newline."""
    return await send_persistent_shell_input_execute(
        shell_id, input_text, enter
    )


@local_tool(
    http_method="POST",
    http_path="/tools/read_persistent_shell_output",
    mcp_scopes=("shell:read",),
)
async def read_persistent_shell_output(
    shell_id: ShellIdArg, lines: LinesArg = 200
) -> ReadPersistentShellOutput:
    """Read recent output from a persistent shell created by bash(pty=true). Pass shell_id returned by bash PTY mode or list_persistent_shells; shell_id is separate from the agent/workspace session_id. Use after send_persistent_shell_input to inspect an interactive or manually managed shell without blocking. For tracked non-interactive jobs from bash(async_=true), use job(poll=[...]) because it works from job_id and refreshes job status. lines defaults to 200 and controls how many recent terminal lines are returned; increase it only when needed for context."""
    return await read_persistent_shell_output_execute(shell_id, lines)


@local_tool(
    http_method="POST",
    http_path="/tools/kill_persistent_shell",
    mcp_scopes=("shell:read", "shell:execute"),
)
async def kill_persistent_shell(
    shell_id: ShellIdArg,
) -> KillPersistentShellOutput:
    """Terminate a persistent shell by shell_id. Use for manually managed shells started with bash(pty=true), such as servers, watches, REPLs, or stuck interactive commands. shell_id is separate from the agent/workspace session_id. For tracked non-interactive jobs from bash(async_=true), use job(cancel=[...]) so the job record is updated. This is destructive for that shell process but does not delete files."""
    return await kill_persistent_shell_execute(shell_id)


@local_tool(
    http_method="GET",
    http_path="/tools/list_persistent_shells",
    mcp_scopes=("shell:read",),
)
async def list_persistent_shells() -> ListPersistentShellsOutput:
    """List active persistent shells created by bash(pty=true). Use this when you need the shell_id before reading, sending input, or killing a manually managed shell. The returned shell_id values are persistent-shell handles, not agent/workspace session_id values; async bash jobs are listed with job(session_id, list_jobs=true) instead."""
    return await list_persistent_shells_execute()
