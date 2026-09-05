"""Controller-side orchestration for the public tracked-job companion tool."""

from collections.abc import Callable
from typing import Any

import workgate.jobs.runtime as jobs_runtime

from ...ops.utils.remote_session import call_remote_session_tool
from ...schemas.result_models.jobs import JobOutput
from ...tool_session.store import (
    UnknownAgentSessionError,
    get_tool_session_store,
)


def _merge_job_counts(*counts: dict[str, int]) -> dict[str, int]:
    """Sum status counts from controller-managed and worker job stores."""
    merged: dict[str, int] = {}
    for source in counts:
        for status, value in source.items():
            merged[status] = merged.get(status, 0) + int(value)
    return merged


def _ordered_job_results(
    requested: list[str],
    local_rows: list[Any],
    remote_rows: list[Any],
    *,
    job_id: Callable[[Any], str],
) -> list[Any]:
    """Merge local and worker action rows in caller-requested order."""
    by_id = {job_id(row): row for row in remote_rows}
    by_id.update({job_id(row): row for row in local_rows})
    return [by_id[item] for item in requested if item in by_id]


async def job_execute(
    session_id: str,
    list_jobs: bool = False,
    poll: list[str] | None = None,
    cancel: list[str] | None = None,
    retry: list[str] | None = None,
    include_finished: bool = True,
    lines: int = 200,
) -> JobOutput:
    """Run one high-level tracked-job companion operation."""
    selected = [poll is not None, cancel is not None, retry is not None]
    if list_jobs and any(selected):
        raise ValueError(
            "list_jobs cannot be combined with poll, cancel, or retry"
        )
    if sum(selected) > 1:
        raise ValueError("poll, cancel, and retry are mutually exclusive")

    try:
        session = get_tool_session_store().touch_session(session_id)
    except UnknownAgentSessionError:
        session = None

    if session is None or session.target != "remote":
        return await jobs_runtime.job_local_execute(
            session_id,
            list_jobs,
            poll,
            cancel,
            retry,
            include_finished,
            lines,
        )

    if list_jobs or not any(selected):
        local = await jobs_runtime.managed_job_list_execute(
            session_id, include_finished
        )
        try:
            remote = JobOutput.model_validate(
                await call_remote_session_tool(
                    session,
                    "job",
                    {
                        "list_jobs": list_jobs,
                        "poll": None,
                        "cancel": None,
                        "retry": None,
                        "include_finished": include_finished,
                        "lines": lines,
                    },
                )
            )
        except Exception as exc:
            if not local.jobs:
                raise
            return JobOutput(
                operation="list",
                jobs=local.jobs,
                counts=local.counts,
                message=(
                    "Remote worker jobs unavailable: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )
        jobs = [*remote.jobs, *local.jobs]
        jobs.sort(key=lambda item: item.created_at, reverse=True)
        return JobOutput(
            operation="list",
            jobs=jobs,
            counts=_merge_job_counts(remote.counts, local.counts),
            message=(
                "No tracked jobs in this session."
                if not jobs
                else "Tracked controller and worker job snapshot for this session."
            ),
        )

    requested = list(poll or cancel or retry or [])
    managed_ids = jobs_runtime.managed_job_id_set(session_id, requested)
    local_ids = [item for item in requested if item in managed_ids]
    remote_ids = [item for item in requested if item not in managed_ids]
    remote = JobOutput(
        operation=(
            "poll"
            if poll is not None
            else "cancel"
            if cancel is not None
            else "retry"
        )
    )
    if remote_ids:
        remote = JobOutput.model_validate(
            await call_remote_session_tool(
                session,
                "job",
                {
                    "poll": remote_ids if poll is not None else None,
                    "cancel": remote_ids if cancel is not None else None,
                    "retry": remote_ids if retry is not None else None,
                    "include_finished": include_finished,
                    "lines": lines,
                },
            )
        )

    if poll is not None:
        local_rows = [
            await jobs_runtime.job_tail_execute(session_id, item, lines)
            for item in local_ids
        ]
        return JobOutput(
            operation="poll",
            outputs=_ordered_job_results(
                requested,
                local_rows,
                remote.outputs,
                job_id=lambda row: row.job.job_id,
            ),
        )
    if cancel is not None:
        local_rows = [
            await jobs_runtime.job_stop_execute(session_id, item)
            for item in local_ids
        ]
        return JobOutput(
            operation="cancel",
            cancelled=_ordered_job_results(
                requested,
                local_rows,
                remote.cancelled,
                job_id=lambda row: row.job.job_id,
            ),
        )
    local_rows = [
        await jobs_runtime.job_retry_execute(session_id, item)
        for item in local_ids
    ]
    return JobOutput(
        operation="retry",
        retried=_ordered_job_results(
            requested,
            local_rows,
            remote.retried,
            job_id=lambda row: row.job_id,
        ),
    )
