"""Explicit agent session operations."""

import subprocess
from pathlib import Path

from ..ops.utils.path import relative_display, workspace_root
from ..schemas.result_models.session import GitSessionInfo, SessionStartOutput
from ..tool_session.store import AgentSession, get_tool_session_store
from .utils.remote_session import start_worker_session

_INSTRUCTION_FILE_NAMES = (
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING",
    "CONTRIBUTING.md",
)


def _git_output(args: list[str], cwd: Path) -> str | None:
    """Run a bounded git orientation command and return stdout text."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
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
    """Return a structured session_start payload for an agent session."""
    workdir = Path(session.workdir)
    return SessionStartOutput(
        session_id=session.session_id,
        target=session.target,
        workdir=session.workdir,
        machine=session.machine,
        created_at=session.created_at,
        updated_at=session.updated_at,
        expires_at=session.expires_at,
        label=session.label,
        workspace_root=str(workspace_root()),
        git=_git_info(workdir)
        if session.target == "local"
        else GitSessionInfo(is_repo=False),
        instruction_files=_instruction_files(workdir)
        if session.target == "local"
        else [],
        message="Use this session_id in subsequent workspace tool calls.",
    )


async def session_start_execute(
    workdir: str,
    target: str = "local",
    machine: str | None = None,
    label: str | None = None,
) -> SessionStartOutput:
    """Create an explicit agent/workspace session."""
    if target == "local":
        session = get_tool_session_store().create_session(
            target="local",
            workdir=workdir,
            machine=machine,
            label=label,
        )
        return _session_output(session)
    if target != "remote":
        raise ValueError("target must be 'local' or 'remote'")
    if not machine:
        raise ValueError("machine is required when target='remote'")

    worker_session = await start_worker_session(
        machine=machine, workdir=workdir, label=label
    )
    worker_session_id = worker_session.get("session_id")
    if not isinstance(worker_session_id, str) or not worker_session_id:
        raise RuntimeError(
            "remote session_start did not return worker session_id"
        )
    remote_workdir = worker_session.get("workdir")
    session = get_tool_session_store().create_session(
        target="remote",
        workdir=str(remote_workdir or workdir),
        machine=machine,
        worker_session_id=worker_session_id,
        label=label,
    )
    return _session_output(session)


def session_change_cwd_execute(
    session_id: str, workdir: str
) -> SessionStartOutput:
    """Change a local session workdir and return refreshed orientation metadata."""
    session = get_tool_session_store().change_session_workdir(
        session_id, workdir
    )
    return _session_output(session)
