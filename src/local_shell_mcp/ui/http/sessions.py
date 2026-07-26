"""Authenticated Human UI inventory for durable agent/workspace sessions."""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from typing import Any

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ...oauth.core.context import MissingOAuthScopeError, require_oauth_scopes
from ...oauth.core.scopes import (
    SCOPE_REMOTE_USE,
    SCOPE_SHELL_READ,
    SCOPE_SHELL_WRITE,
)
from ...tool_session.store import (
    SESSION_ACTIVE_WINDOW_S,
    AgentSession,
    get_tool_session_store,
)
from .common import bounded_text, json_error, require_remote_machine

UI_SESSION_MACHINE_MAX_BYTES = 255
UI_SESSION_MAX_ENTRIES = 2_000


def _json_ok(data: Any = None, message: str = "") -> JSONResponse:
    return JSONResponse({"ok": True, "message": message, "data": data})


def _machine_arg(value: Any) -> str:
    return bounded_text(
        value,
        field="machine",
        max_bytes=UI_SESSION_MACHINE_MAX_BYTES,
        default="local",
        allow_empty=False,
    )


def _require_scopes(machine: str, *, write: bool = False) -> None:
    required = [SCOPE_SHELL_READ]
    if write:
        required.append(SCOPE_SHELL_WRITE)
    if machine != "local":
        required.append(SCOPE_REMOTE_USE)
    try:
        require_oauth_scopes(tuple(required))
    except MissingOAuthScopeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _belongs_to_machine(session: AgentSession, machine: str) -> bool:
    if machine == "local":
        return session.target == "local"
    return session.target == "remote" and session.machine == machine


def _session_payload(session: AgentSession, *, now: float) -> dict[str, Any]:
    payload = asdict(session)
    payload.pop("worker_session_id", None)
    payload["active"] = session.updated_at >= now - SESSION_ACTIVE_WINDOW_S
    payload["termination_requested"] = (
        session.termination_requested_at is not None
    )
    return payload


def _bool_arg(value: Any, *, default: bool = False) -> bool:
    if value in {None, ""}:
        return default
    normalized = str(value).casefold().strip()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("include_inactive must be a boolean")


def _session_for_machine(session_id: str, machine: str) -> AgentSession:
    session = get_tool_session_store().require_session(session_id)
    if not _belongs_to_machine(session, machine):
        raise ValueError(
            f"session {session_id} does not belong to machine {machine}"
        )
    return session


async def api_sessions(request: Request) -> Response:
    """Return durable public agent sessions bound to one machine."""
    try:
        machine = _machine_arg(request.query_params.get("machine"))
        _require_scopes(machine)
        include_inactive = _bool_arg(
            request.query_params.get("include_inactive")
        )
        if machine != "local":
            require_remote_machine(machine)
        sessions = await asyncio.to_thread(
            get_tool_session_store().list_sessions
        )
        now = time.time()
        rows = [
            _session_payload(session, now=now)
            for session in sessions
            if _belongs_to_machine(session, machine)
            and (
                include_inactive
                or session.updated_at >= now - SESSION_ACTIVE_WINDOW_S
            )
        ][:UI_SESSION_MAX_ENTRIES]
        return _json_ok(
            {
                "machine": machine,
                "remote": machine != "local",
                "sessions": rows,
                "count": len(rows),
                "include_inactive": include_inactive,
                "active_window_hours": SESSION_ACTIVE_WINDOW_S // 3600,
            }
        )
    except HTTPException:
        raise
    except ConnectionError as exc:
        return json_error(exc, status_code=503)
    except RuntimeError as exc:
        return json_error(exc, status_code=502)
    except Exception as exc:
        return json_error(exc)


async def api_session_action(request: Request) -> Response:
    """Apply one explicit Human UI control-plane action to a session."""
    try:
        action = str(request.path_params.get("action") or "").casefold()
        if action != "terminate":
            return json_error(
                ValueError(f"unsupported session action: {action}"),
                status_code=404,
            )
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("session action body must be a JSON object")
        machine = _machine_arg(payload.get("machine"))
        session_id = bounded_text(
            payload.get("session_id"),
            field="session_id",
            max_bytes=32,
            allow_empty=False,
        )
        _require_scopes(machine, write=True)
        if machine != "local":
            require_remote_machine(machine)
        _session_for_machine(session_id, machine)
        session = await asyncio.to_thread(
            get_tool_session_store().request_termination, session_id
        )
        return _json_ok(
            {
                "machine": machine,
                "session": _session_payload(session, now=time.time()),
            },
            message="Session marked for immediate termination",
        )
    except HTTPException:
        raise
    except ConnectionError as exc:
        return json_error(exc, status_code=503)
    except RuntimeError as exc:
        return json_error(exc, status_code=502)
    except Exception as exc:
        return json_error(exc)
