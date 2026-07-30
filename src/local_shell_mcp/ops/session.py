"""Explicit agent session operations."""

import asyncio
import subprocess
from pathlib import Path
from typing import Any, Literal, overload

from ..config.settings import get_settings
from ..ops.utils.path import relative_display, workspace_root
from ..schemas.result_models.jobs import JobStartOutput
from ..schemas.result_models.session import (
    GitSessionInfo,
    SessionCopyOutput,
    SessionEndOutput,
    SessionStartOutput,
)
from ..tool_session.environment import collect_session_environment
from ..tool_session.lifecycle import session_lifecycle_lock
from ..tool_session.store import AgentSession, get_tool_session_store

_INSTRUCTION_FILE_NAMES = (
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING",
    "CONTRIBUTING.md",
)


async def start_worker_session(
    *,
    machine: str,
    workdir: str,
    label: str | None = None,
) -> dict[str, Any]:
    """Lazily dispatch remote session creation without importing the control plane."""
    from .utils.remote_session import (
        start_worker_session as start_worker_session_impl,
    )

    return await start_worker_session_impl(
        machine=machine,
        workdir=workdir,
        label=label,
    )


async def end_worker_session(*, machine: str, worker_session_id: str) -> None:
    """Release a worker session when controller registration cannot complete."""
    from .utils.remote_session import (
        end_worker_session as end_worker_session_impl,
    )

    await end_worker_session_impl(
        machine=machine, worker_session_id=worker_session_id
    )


def _git_output(args: list[str], cwd: Path) -> str | None:
    """Run a bounded git orientation command and return stdout text."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _git_info(cwd: Path) -> GitSessionInfo:
    """Return cheap git orientation for a local workdir."""
    root = _git_output(["rev-parse", "--show-toplevel"], cwd)
    if root is None:
        return GitSessionInfo(is_repo=False)
    branch = _git_output(["branch", "--show-current"], cwd)
    if not branch:
        branch = _git_output(["rev-parse", "--short", "HEAD"], cwd)
    dirty = None
    status = _git_output(["status", "--porcelain"], cwd)
    if status is not None:
        dirty = bool(status)
    return GitSessionInfo(is_repo=True, root=root, branch=branch, dirty=dirty)


def _instruction_files(workdir: Path) -> list[str]:
    """Discover nearby project instruction files without reading their contents."""
    root = workspace_root()
    found: list[str] = []
    current = workdir.resolve()
    while True:
        try:
            current.relative_to(root)
        except ValueError:
            break
        for name in _INSTRUCTION_FILE_NAMES:
            candidate = current / name
            if candidate.is_file():
                found.append(relative_display(candidate))
        if current == root or current.parent == current:
            break
        current = current.parent
    return found


def _session_output(session: AgentSession) -> SessionStartOutput:
    """Return a structured session payload for a locally owned agent session."""
    workdir = Path(session.workdir)
    settings = get_settings()
    return SessionStartOutput(
        session_id=session.session_id,
        target=session.target,
        workdir=session.workdir,
        machine=session.machine,
        created_at=session.created_at,
        updated_at=session.updated_at,
        expires_at=session.expires_at,
        label=session.label,
        workspace_root=str(settings.workspace_root),
        git=_git_info(workdir),
        instruction_files=_instruction_files(workdir),
        environment=collect_session_environment(
            settings,
            workdir=session.workdir,
            target=session.target,
            machine=session.machine,
        ),
        message="Use this session_id in subsequent workspace tool calls.",
    )


def _rebind_remote_output(
    worker_output: SessionStartOutput,
    control_session: AgentSession,
) -> SessionStartOutput:
    """Bind worker-generated orientation to the controller's public session id."""
    workspace = worker_output.environment.workspace.model_copy(
        update={
            "target": "remote",
            "machine": control_session.machine,
            "workdir": worker_output.workdir,
        }
    )
    environment = worker_output.environment.model_copy(
        update={"workspace": workspace}
    )
    return worker_output.model_copy(
        update={
            "session_id": control_session.session_id,
            "target": "remote",
            "machine": control_session.machine,
            "created_at": control_session.created_at,
            "updated_at": control_session.updated_at,
            "expires_at": control_session.expires_at,
            "label": control_session.label,
            "environment": environment,
        }
    )


def _start_local_session(
    *, workdir: str, machine: str | None, label: str | None
) -> SessionStartOutput:
    """Create and orient one local session outside the async transport loop."""
    session = get_tool_session_store().create_session(
        target="local",
        workdir=workdir,
        machine=machine,
        label=label,
    )
    return _session_output(session)


async def session_start_execute(
    workdir: str,
    target: str = "local",
    machine: str | None = None,
    label: str | None = None,
) -> SessionStartOutput:
    """Create an explicit agent/workspace session."""
    if target in {"local", "remote"}:
        from ..jobs.runtime import job_reconcile_shell_jobs_execute

        await job_reconcile_shell_jobs_execute()
    if target == "local":
        return await asyncio.to_thread(
            _start_local_session,
            workdir=workdir,
            machine=machine,
            label=label,
        )
    if target != "remote":
        raise ValueError("target must be 'local' or 'remote'")
    if not machine:
        raise ValueError("machine is required when target='remote'")

    worker_session = await start_worker_session(
        machine=machine, workdir=workdir, label=label
    )
    try:
        worker_output = SessionStartOutput.model_validate(worker_session)
    except Exception as exc:
        raise RuntimeError(
            "remote session_start returned invalid structured orientation"
        ) from exc
    worker_session_id = worker_output.session_id
    if not worker_session_id:
        raise RuntimeError(
            "remote session_start did not return worker session_id"
        )
    try:
        session = get_tool_session_store().create_session(
            target="remote",
            workdir=worker_output.workdir,
            machine=machine,
            worker_session_id=worker_session_id,
            label=label,
        )
    except Exception as admission_error:
        try:
            await end_worker_session(
                machine=machine, worker_session_id=worker_session_id
            )
        except Exception as cleanup_error:
            raise RuntimeError(
                "controller session admission failed and the worker session "
                f"could not be released: {cleanup_error}"
            ) from admission_error
        raise
    return _rebind_remote_output(worker_output, session)


def _change_local_session_cwd(
    session_id: str, workdir: str
) -> SessionStartOutput:
    """Change and orient one local session outside the async transport loop."""
    session = get_tool_session_store().change_session_workdir(
        session_id, workdir
    )
    return _session_output(session)


async def session_change_cwd_execute(
    session_id: str, workdir: str
) -> SessionStartOutput:
    """Serialize one local or remote workdir transition with session teardown."""
    async with session_lifecycle_lock(session_id):
        return await _session_change_cwd_execute_unlocked(session_id, workdir)


async def _session_change_cwd_execute_unlocked(
    session_id: str, workdir: str
) -> SessionStartOutput:
    """Change a local or remote workdir while the lifecycle lock is held."""
    store = get_tool_session_store()
    session = store.require_session(session_id)
    if session.target == "local":
        return await asyncio.to_thread(
            _change_local_session_cwd, session_id, workdir
        )
    from .utils.remote_session import call_remote_session_tool

    payload = await call_remote_session_tool(
        session,
        "session_change_cwd",
        {"workdir": workdir},
    )
    try:
        worker_output = SessionStartOutput.model_validate(payload)
    except Exception as exc:
        raise RuntimeError(
            "remote session_change_cwd returned invalid structured orientation"
        ) from exc
    updated = store.update_remote_session_workdir(
        session_id, worker_output.workdir
    )
    return _rebind_remote_output(worker_output, updated)


async def _stop_owned_jobs(session_id: str) -> list[str]:
    """Stop every active tracked job before its owning session disappears."""
    from ..jobs.runtime import (
        CONFIRMED_TERMINAL_STATUSES,
        _job_list_execute_unlocked,
        _job_stop_execute_unlocked,
        job_stop_managed_references_execute,
    )

    listed = await _job_list_execute_unlocked(session_id, include_finished=True)
    stopped: list[str] = []
    for job in listed.jobs:
        if job.status in CONFIRMED_TERMINAL_STATUSES:
            continue
        result = await _job_stop_execute_unlocked(session_id, job.job_id)
        if result.killed or result.job.status in CONFIRMED_TERMINAL_STATUSES:
            stopped.append(job.job_id)
            continue
        raise RuntimeError(
            "tracked job could not be confirmed stopped: "
            f"{job.job_id}: status={result.job.status!r}"
        )
    referenced = await job_stop_managed_references_execute(
        session_id,
        managed_kind="session-copy",
        payload_key="dst_session_id",
    )
    stopped.extend(job_id for job_id in referenced if job_id not in stopped)
    return stopped


async def _stop_owned_shells(session_id: str) -> list[str]:
    """Stop every persistent shell assigned to one explicit session."""
    from .shell import (
        authoritative_persistent_shell_ids_execute,
        kill_persistent_shell_execute,
        list_owned_persistent_shell_ids_execute,
    )

    discovered_shell_ids = await list_owned_persistent_shell_ids_execute(
        session_id
    )
    if discovered_shell_ids is None:
        raise RuntimeError(
            "persistent shell ownership could not be determined; refusing to "
            "remove the session"
        )
    store = get_tool_session_store()
    store.reconcile_session_persistent_shells(
        session_id, set(discovered_shell_ids)
    )
    shell_ids = tuple(dict.fromkeys(discovered_shell_ids))
    stopped: list[str] = []
    for shell_id in shell_ids:
        current_owned = await list_owned_persistent_shell_ids_execute(
            session_id
        )
        if current_owned is None:
            raise RuntimeError(
                "persistent shell ownership could not be determined; refusing "
                "to remove the session"
            )
        if shell_id not in current_owned:
            store.reconcile_session_persistent_shells(
                session_id, set(current_owned)
            )
            continue
        result = await kill_persistent_shell_execute(shell_id)
        if not result.killed:
            active_shell_ids = (
                await authoritative_persistent_shell_ids_execute()
            )
            if active_shell_ids is None or shell_id in active_shell_ids:
                raise RuntimeError(
                    f"persistent shell could not be stopped: {shell_id}: "
                    f"{result.stderr or 'unknown backend error'}"
                )
        stopped.append(shell_id)
    return stopped


async def session_end_execute(
    session_id: str, *, force: bool = False
) -> SessionEndOutput:
    """End one session while excluding concurrent job admission and retry."""
    async with session_lifecycle_lock(session_id):
        return await _session_end_execute_unlocked(session_id, force=force)


async def _session_end_execute_unlocked(
    session_id: str, *, force: bool = False
) -> SessionEndOutput:
    """Stop owned work and remove one local or remote session."""
    store = get_tool_session_store()
    session = store.prepare_session_termination(session_id)
    stopped_jobs = await _stop_owned_jobs(session_id)
    stopped_shells: list[str] = []
    if session.target == "local":
        stopped_shells = await _stop_owned_shells(session_id)
    remote_cleanup_succeeded: bool | None = None
    force_released = False
    if session.target == "remote":
        from .utils.remote_session import call_remote_session_tool

        try:
            await call_remote_session_tool(session, "session_end", {})
        except Exception:
            remote_cleanup_succeeded = False
            if not force:
                raise
            force_released = True
        else:
            remote_cleanup_succeeded = True
    ended = store.end_session(session_id)
    return SessionEndOutput(
        session_id=ended.session_id,
        target=ended.target,
        machine=ended.machine,
        ended=True,
        stopped_jobs=stopped_jobs,
        stopped_shells=stopped_shells,
        remote_cleanup_succeeded=remote_cleanup_succeeded,
        force_released=force_released,
    )


@overload
async def session_copy_execute(
    src_session_id: str,
    src_path: str,
    dst_session_id: str,
    dst_path: str,
    kind: Literal["auto", "file", "dir"] = "auto",
    overwrite: bool = True,
    chunk_size: int | None = None,
    background: Literal[False] = False,
) -> SessionCopyOutput:
    """Return the synchronous copy result when background mode is disabled."""
    ...


@overload
async def session_copy_execute(
    src_session_id: str,
    src_path: str,
    dst_session_id: str,
    dst_path: str,
    kind: Literal["auto", "file", "dir"] = "auto",
    overwrite: bool = True,
    chunk_size: int | None = None,
    background: Literal[True] = True,
) -> JobStartOutput:
    """Return a managed job when background mode is explicitly enabled."""
    ...


@overload
async def session_copy_execute(
    src_session_id: str,
    src_path: str,
    dst_session_id: str,
    dst_path: str,
    kind: Literal["auto", "file", "dir"] = "auto",
    overwrite: bool = True,
    chunk_size: int | None = None,
    background: bool = False,
) -> SessionCopyOutput | JobStartOutput:
    """Return a synchronous copy or managed job for a runtime boolean flag."""
    ...


async def session_copy_execute(
    src_session_id: str,
    src_path: str,
    dst_session_id: str,
    dst_path: str,
    kind: Literal["auto", "file", "dir"] = "auto",
    overwrite: bool = True,
    chunk_size: int | None = None,
    background: bool = False,
) -> SessionCopyOutput | JobStartOutput:
    """Copy synchronously or start a managed background copy job."""
    from .utils.session_copy import (
        session_copy_execute as _session_copy_execute,
    )
    from .utils.session_copy import session_copy_job_execute

    if background:
        return await session_copy_job_execute(
            src_session_id,
            src_path,
            dst_session_id,
            dst_path,
            kind,
            overwrite,
            chunk_size,
        )
    return await _session_copy_execute(
        src_session_id,
        src_path,
        dst_session_id,
        dst_path,
        kind,
        overwrite,
        chunk_size,
    )
