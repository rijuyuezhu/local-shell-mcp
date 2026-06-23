"""Typed structured outputs for tracked bash job tools."""

from typing import Literal

from pydantic import BaseModel, Field

type JobStatus = Literal["running", "exited", "stopped", "lost", "unknown"]


class JobInfo(BaseModel):
    """One tracked command owned by an explicit agent session."""

    job_id: str = Field(
        description="Stable tracked job identifier. Use this with the `job` companion poll, cancel, or retry actions in the same session."
    )
    name: str = Field(
        description="Human-readable job name, or the generated job_id when no name was provided."
    )
    status: JobStatus = Field(
        description="Tracked job status: running while the background command can still be inspected; exited when it disappears naturally; stopped when cancelled; lost when output/control cannot be inspected."
    )
    command: str = Field(
        description="Original shell command used to start the job. The retry action reuses this command."
    )
    cwd: str = Field(
        description="Working directory used to start the job. The retry action reuses this directory when it remains inside the owning session workdir."
    )
    session_id: str = Field(
        description="Agent/workspace session_id that owns this tracked job."
    )
    created_at: float = Field(
        description="Unix timestamp when the tracked job record was created."
    )
    updated_at: float = Field(
        description="Unix timestamp when the tracked job record was last updated."
    )
    last_started_at: float = Field(
        description="Unix timestamp when the current or most recent attempt was started."
    )
    attempts: int = Field(
        description="Number of times this tracked job has been started, including retries."
    )


class JobStartOutput(JobInfo):
    """Tracked job record created after starting a command."""


class JobRetryOutput(JobInfo):
    """Tracked job record after restarting its original command and cwd."""


class JobListOutput(BaseModel):
    """Tracked job inventory for one agent session."""

    jobs: list[JobInfo] = Field(
        description="Tracked jobs for the requested session, sorted newest first, optionally excluding terminal jobs."
    )
    counts: dict[str, int] = Field(
        description="Counts for tracked jobs owned by the requested session, before include_finished filtering."
    )


class JobTailOutput(BaseModel):
    """Recent terminal output for one tracked job."""

    job: JobInfo = Field(
        description="Tracked job metadata after status refresh."
    )
    output: str = Field(
        default="",
        description="Recent output captured for the tracked job. Full job logs are not persisted separately.",
    )
    message: str | None = Field(
        default=None,
        description="Diagnostic message when output is unavailable, for example after the job exits or is lost.",
    )


class JobStopOutput(BaseModel):
    """Result of stopping one tracked job."""

    job: JobInfo = Field(description="Tracked job metadata after stop attempt.")
    killed: bool = Field(description="Whether the tracked job was stopped.")
    stderr: str = Field(
        default="",
        description="Backend stderr from the stop attempt, when reported.",
    )


class JobOutput(BaseModel):
    """Unified companion result for tracked bash jobs."""

    operation: Literal["list", "poll", "cancel", "retry"] = Field(
        description="Job operation performed by the unified job companion tool."
    )
    jobs: list[JobInfo] = Field(
        default_factory=list,
        description="Tracked job rows returned for list-style snapshots.",
    )
    counts: dict[str, int] = Field(
        default_factory=dict,
        description="Tracked job counts by status when a list snapshot was read.",
    )
    outputs: list[JobTailOutput] = Field(
        default_factory=list,
        description="Recent output/status entries returned for inspected jobs.",
    )
    cancelled: list[JobStopOutput] = Field(
        default_factory=list,
        description="Stop results returned for cancelled jobs.",
    )
    retried: list[JobRetryOutput] = Field(
        default_factory=list,
        description="Restarted job rows returned for retried jobs.",
    )
    message: str | None = Field(
        default=None,
        description="Optional diagnostic or usage note.",
    )
