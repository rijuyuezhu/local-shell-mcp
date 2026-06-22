"""Tracked persistent-shell job MCP tool registry."""

from ...ops.jobs import (
    job_list_execute,
    job_retry_execute,
    job_start_execute,
    job_stop_execute,
    job_tail_execute,
)
from ...schemas.input_models.jobs import (
    IncludeFinishedArg,
    JobCommandArg,
    JobCwdArg,
    JobIdArg,
    JobNameArg,
    JobTailLinesArg,
)
from ...schemas.input_models.shell import ToolExplanationArg, ToolPurposeArg
from ...schemas.result_models.jobs import (
    JobListOutput,
    JobRetryOutput,
    JobStartOutput,
    JobStopOutput,
    JobTailOutput,
)
from ..declarative import DeclarativeToolRegistry
from ..purpose import audit_tool_purpose


class JobToolRegistry(DeclarativeToolRegistry):
    """Register tracked command tools backed by persistent shell sessions."""

    name = "jobs"
    """Registry group name used for tool-surface organization."""


local_tool = JobToolRegistry.get_tool_decorator()


@local_tool(
    http_method="POST",
    http_path="/tools/jobs/start",
    mcp_scopes=("shell:read", "shell:execute"),
)
async def job_start(
    command: JobCommandArg,
    cwd: JobCwdArg = ".",
    name: JobNameArg = None,
    purpose: ToolPurposeArg = None,
    explanation: ToolExplanationArg = None,
) -> JobStartOutput:
    """Start a non-interactive command as a tracked job backed by a persistent shell session. Use job_start for long-running builds, tests, servers, watches, experiments, and other commands you want to manage by job_id with job_list, job_tail, job_stop, or job_retry. Use start_persistent_shell instead when the process is interactive, needs later send_persistent_shell_input calls, or should be managed directly by session_id. Use run_shell_command for short bounded commands that should finish promptly."""
    audit_tool_purpose("job_start", purpose, explanation)
    return await job_start_execute(command, cwd, name)


@local_tool(
    http_method="POST",
    http_path="/tools/jobs/list",
    mcp_scopes=("shell:read", "shell:execute"),
)
async def job_list(
    include_finished: IncludeFinishedArg = True,
) -> JobListOutput:
    """List tracked non-interactive jobs and status counts. Use this for commands started with job_start/job_retry; use list_persistent_shells for manually managed interactive sessions. Each job is a recorded persistent-shell command, not a separate scheduler queue; status is refreshed from the backing shell session when possible."""
    return await job_list_execute(include_finished)


@local_tool(
    http_method="POST",
    http_path="/tools/jobs/tail",
    mcp_scopes=("shell:read", "shell:execute"),
)
async def job_tail(
    job_id: JobIdArg,
    lines: JobTailLinesArg = 200,
) -> JobTailOutput:
    """Read recent terminal output for a tracked non-interactive job by job_id. Use this instead of read_persistent_shell_output for jobs started with job_start because it refreshes job status and hides the backing session_id. Full logs are not persisted separately, so output may be unavailable after the backing session exits or is lost."""
    return await job_tail_execute(job_id, lines)


@local_tool(
    http_method="POST",
    http_path="/tools/jobs/stop",
    mcp_scopes=("shell:read", "shell:execute"),
)
async def job_stop(job_id: JobIdArg) -> JobStopOutput:
    """Stop a tracked non-interactive job by killing its backing persistent shell session and updating the job record. Use kill_persistent_shell only for manually managed sessions started with start_persistent_shell. The job record remains available for list and retry."""
    return await job_stop_execute(job_id)


@local_tool(
    http_method="POST",
    http_path="/tools/jobs/retry",
    mcp_scopes=("shell:read", "shell:execute"),
)
async def job_retry(
    job_id: JobIdArg,
    purpose: ToolPurposeArg = None,
    explanation: ToolExplanationArg = None,
) -> JobRetryOutput:
    """Restart a terminal tracked job with its original command and working directory. Use this for failed or completed non-interactive jobs started with job_start; for interactive sessions, start a new persistent shell manually instead. This creates a new backing persistent shell session, increments attempts, and keeps the same job_id."""
    audit_tool_purpose("job_retry", purpose, explanation)
    return await job_retry_execute(job_id)
