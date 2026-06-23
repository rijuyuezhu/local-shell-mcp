"""Bash tool registry."""

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
    """Register the bash tool."""

    name = "bash"
    """Registry group name used for tool-surface organization."""


local_tool = BashToolRegistry.get_tool_decorator()


def _bash_description(context: McpToolContext) -> str:
    settings = context.settings
    return f"""Run terminal commands for builds, tests, package managers, git inspection, scripts, and other shell work. Prefer the `cwd` argument over embedded directory changes; use `env` for multiline or quote-heavy values. Set `async_=true` for long-running non-interactive work tracked by job id, and `pty=true` only for interactive programs, REPLs, servers, or commands that need later input. Use built-in `search` for source/content discovery so output carries edit-grounding metadata. Current bounded command timeout default/cap: {settings.run_shell_default_timeout_s}/{settings.run_shell_max_timeout_s} seconds."""


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
