"""Per-operation typed views of durable tool-session records."""

from dataclasses import dataclass
from typing import Literal

from .records import AgentSession, valid_session_id


@dataclass(frozen=True)
class LocalSessionBinding:
    """Validated controller-local execution coordinates for one operation."""

    session_id: str
    workdir: str
    target: Literal["local"] = "local"


@dataclass(frozen=True)
class RemoteSessionBinding:
    """Validated remote-worker execution coordinates for one operation."""

    session_id: str
    workdir: str
    machine: str
    worker_session_id: str
    target: Literal["remote"] = "remote"


type SessionBinding = LocalSessionBinding | RemoteSessionBinding


def binding_from_record(session: AgentSession) -> SessionBinding:
    """Purely validate and convert one durable record into a typed binding."""
    if valid_session_id(session.session_id) is None:
        raise ValueError("session record contains an invalid session_id")
    if not session.workdir:
        raise ValueError("session record contains an empty workdir")
    match session.target:
        case "local":
            if (
                session.machine is not None
                or session.worker_session_id is not None
            ):
                raise ValueError(
                    "local session record contains a remote worker binding"
                )
            return LocalSessionBinding(
                session_id=session.session_id,
                workdir=session.workdir,
            )
        case "remote":
            if not session.machine or not session.worker_session_id:
                raise ValueError(
                    "remote session record is missing its worker binding"
                )
            return RemoteSessionBinding(
                session_id=session.session_id,
                workdir=session.workdir,
                machine=session.machine,
                worker_session_id=session.worker_session_id,
            )
        case _:
            raise ValueError(f"unsupported session target: {session.target!r}")
