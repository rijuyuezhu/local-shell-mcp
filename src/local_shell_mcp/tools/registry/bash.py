"""High-level bash facade tool registry."""

from ...ops.bash import bash_execute
from ...schemas.input_models.bash import (
    BashAsyncArg,
    BashCommandArg,
    BashCwdArg,
    BashEnvArg,
    BashMaxOutputBytesArg,
    BashNameArg,
    BashPtyArg,
    BashTimeoutArg,
)
from ...schemas.input_models.shell import ToolExplanationArg, ToolPurposeArg
from ...schemas.result_models.bash import BashOutput
from ..contracts import McpToolContext
from ..declarative import DeclarativeToolRegistry
from ..purpose import audit_tool_purpose


class BashToolRegistry(DeclarativeToolRegistry):
    """Register high-level bash facade tools."""

    name = "bash"
    """Registry group name used for tool-surface organization."""


local_tool = BashToolRegistry.get_tool_decorator()


def _bash_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Run shell commands through one agent-oriented facade. By default bash runs a bounded non-interactive command like run_shell_command. Set async_=true for long-running non-interactive work that should be tracked by job_id. Set pty=true for interactive programs, REPLs, servers, or commands that need later input through persistent-shell tools. Current bounded command timeout default/cap: {settings.run_shell_default_timeout_s}/{settings.run_shell_max_timeout_s} seconds."""


@local_tool(
    http_method="POST",
    http_path="/tools/bash",
    description=_bash_description,
    mcp_scopes=("shell:read", "shell:execute"),
)
async def bash(
    command: BashCommandArg,
    cwd: BashCwdArg = ".",
    timeout_s: BashTimeoutArg = None,
    max_output_bytes: BashMaxOutputBytesArg = None,
    env: BashEnvArg = None,
    async_: BashAsyncArg = False,
    pty: BashPtyArg = False,
    name: BashNameArg = None,
    purpose: ToolPurposeArg = None,
    explanation: ToolExplanationArg = None,
) -> BashOutput:
    """Run a shell command via bounded, job, or PTY mode."""
    audit_tool_purpose("bash", purpose, explanation)
    return await bash_execute(
        command,
        cwd,
        timeout_s,
        max_output_bytes,
        env,
        async_,
        pty,
        name,
    )
