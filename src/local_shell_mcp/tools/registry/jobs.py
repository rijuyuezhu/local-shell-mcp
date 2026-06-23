"""Tracked bash job companion tool registry."""

from ...ops.jobs import (
    job_list_execute,
    job_retry_execute,
    job_stop_execute,
    job_tail_execute,
)
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
    """Manage tracked async bash jobs through one oh-my-pi-style companion tool."""
    selected = [poll is not None, cancel is not None, retry is not None]
    if list_jobs and any(selected):
        raise ValueError(
            "list_jobs cannot be combined with poll, cancel, or retry"
        )
    if sum(selected) > 1:
        raise ValueError("poll, cancel, and retry are mutually exclusive")

    if list_jobs or not any(selected):
        result = await job_list_execute(include_finished)
        return JobOutput(
            operation="list",
            jobs=result.jobs,
            counts=result.counts,
            message=(
                "No tracked bash jobs."
                if not result.jobs
                else "Tracked bash job snapshot."
            ),
        )

    if poll is not None:
        outputs = [await job_tail_execute(job_id, lines) for job_id in poll]
        return JobOutput(operation="poll", outputs=outputs)

    if cancel is not None:
        cancelled = [await job_stop_execute(job_id) for job_id in cancel]
        return JobOutput(operation="cancel", cancelled=cancelled)

    if retry is not None:
        retried = [await job_retry_execute(job_id) for job_id in retry]
        return JobOutput(operation="retry", retried=retried)

    raise AssertionError("unreachable job action state")
