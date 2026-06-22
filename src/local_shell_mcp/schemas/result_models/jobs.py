"""Typed structured outputs for tracked persistent-shell job tools."""

from typing import Literal

from pydantic import BaseModel, Field

type JobStatus = Literal["running", "exited", "stopped", "lost", "unknown"]


class JobInfo(BaseModel):
    """One tracked command backed by a persistent shell session."""

    job_id: str = Field(
        description="Stable tracked job identifier. Use this with job_tail, job_stop, or job_retry."
    )
    name: str = Field(
        description="Human-readable job name, or the generated job_id when no name was provided."
    )
    status: JobStatus = Field(
        description="Tracked job status: running while the backing session exists; exited when it disappears naturally; stopped when killed by job_stop; lost when the backing session cannot be inspected."
    )
    command: str = Field(
        description="Original shell command used to start the job. job_retry reuses this command."
    )
    cwd: str = Field(
        description="Working directory used to start the job. job_retry reuses this directory."
    )
    session_id: str = Field(
        description="Backing persistent shell session id. This is exposed for diagnostics; prefer job_* tools for tracked-job operations."
    )
    backend: str | None = Field(
        default=None,
        description="Persistent shell backend, such as tmux, when reported by the shell layer.",
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
    """Tracked job inventory."""

    jobs: list[JobInfo] = Field(
        description="Tracked jobs sorted newest first, optionally excluding terminal jobs."
    )
    counts: dict[str, int] = Field(
        description="Counts for all tracked jobs by status, before include_finished filtering."
    )


class JobTailOutput(BaseModel):
    """Recent terminal output for one tracked job."""

    job: JobInfo = Field(
        description="Tracked job metadata after status refresh."
    )
    output: str = Field(
        default="",
        description="Recent output captured from the backing persistent shell. Full job logs are not persisted separately.",
    )
    message: str | None = Field(
        default=None,
        description="Diagnostic message when output is unavailable, for example after the backing session exits or is lost.",
    )


class JobStopOutput(BaseModel):
    """Result of stopping one tracked job."""

    job: JobInfo = Field(description="Tracked job metadata after stop attempt.")
    killed: bool = Field(
        description="Whether the backing persistent shell session was killed."
    )
    stderr: str = Field(
        default="",
        description="Backend stderr from the stop attempt, when reported by the shell layer.",
    )
