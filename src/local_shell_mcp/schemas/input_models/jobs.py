"""Typed input annotations for tracked bash job tools."""

from typing import Annotated

from pydantic import Field, StringConstraints

JobCommandArg = Annotated[
    str,
    StringConstraints(min_length=1),
    Field(
        description="Non-empty shell command to start as a tracked job. Jobs are started through bash(async_=true); use bash(pty=true) when you need an interactive session that receives later input."
    ),
]
JobCwdArg = Annotated[
    str,
    Field(
        description="Working directory for the tracked job. Relative paths resolve inside the agent session workdir."
    ),
]
JobNameArg = Annotated[
    str | None,
    StringConstraints(min_length=1, max_length=80),
    Field(
        default=None,
        description="Optional human-readable job name used for list output. Omit to use the generated job_id.",
    ),
]
JobIdArg = Annotated[
    str,
    StringConstraints(min_length=1),
    Field(
        description="Tracked job identifier returned by `bash(async_=true)` or `job` in the same agent session."
    ),
]
IncludeFinishedArg = Annotated[
    bool,
    Field(
        description="Whether to include terminal jobs with exited, stopped, or lost status. Set false to show only active jobs."
    ),
]
JobTailLinesArg = Annotated[
    int,
    Field(
        ge=1,
        le=5000,
        description="Number of recent terminal lines to capture for a tracked job. Output is available only while the background job can still be inspected.",
    ),
]


JobListSnapshotArg = Annotated[
    bool,
    Field(
        description="Whether to return a snapshot of tracked bash jobs owned by this session. Omit all other job actions to list by default."
    ),
]
JobPollIdsArg = Annotated[
    list[str] | None,
    Field(
        default=None,
        description="Tracked bash job ids in this session whose latest output/status should be inspected. Use only when you need to check specific async bash work.",
    ),
]
JobCancelIdsArg = Annotated[
    list[str] | None,
    Field(
        default=None,
        description="Tracked bash job ids in this session to stop because they are stalled, hung, or no longer needed.",
    ),
]
JobRetryIdsArg = Annotated[
    list[str] | None,
    Field(
        default=None,
        description="Tracked bash job ids in this session to restart with their original command and working directory.",
    ),
]
