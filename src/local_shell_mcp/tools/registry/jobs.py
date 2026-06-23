"""Tracked bash job companion tool registry."""

from ...ops.jobs import job_execute
from ...schemas.input_models.jobs import (
    IncludeFinishedArg,
    JobCancelIdsArg,
    JobListSnapshotArg,
    JobPollIdsArg,
    JobRetryIdsArg,
    JobTailLinesArg,
)
from ...schemas.result_models.jobs import JobOutput
from ..declarative import DeclarativeToolRegistry


class JobToolRegistry(DeclarativeToolRegistry):
    """Register bash async job companion tools."""

    name = "jobs"
    """Registry group name used for tool-surface organization."""


local_tool = JobToolRegistry.get_tool_decorator()


def _job_description(_context: object) -> str:
    return """Inspect, read output from, stop, or retry async bash jobs.

Results for `bash(async_=true)` are tracked by job id. Reach for this companion tool only when you need to intervene: list running work, inspect recent output, stop stalled work, or retry a finished command. Starting work belongs in `bash`, not `job`.

Call with no action, or with `list_jobs=true`, to list jobs. Use `poll=[id]` to inspect recent output/status for specific jobs, `cancel=[id]` to stop jobs, or `retry=[id]` to restart jobs with their original command and working directory. Do not combine actions in one call."""


@local_tool(
    http_method="POST",
    http_path="/tools/job",
    description=_job_description,
    mcp_scopes=("shell:read", "shell:execute"),
)
async def job(
    list_jobs: JobListSnapshotArg = False,
    poll: JobPollIdsArg = None,
    cancel: JobCancelIdsArg = None,
    retry: JobRetryIdsArg = None,
    include_finished: IncludeFinishedArg = True,
    lines: JobTailLinesArg = 200,
) -> JobOutput:
    """Manage tracked async bash jobs through one companion tool."""
    return await job_execute(
        list_jobs, poll, cancel, retry, include_finished, lines
    )
