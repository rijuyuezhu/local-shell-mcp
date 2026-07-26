"""Authenticated Human UI inventory for durable agent/workspace sessions."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ...oauth.core.context import MissingOAuthScopeError, require_oauth_scopes
from ...oauth.core.scopes import SCOPE_REMOTE_USE, SCOPE_SHELL_READ
from ...tool_session.store import AgentSession, get_tool_session_store
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


def _require_scopes(machine: str) -> None:
    required = [SCOPE_SHELL_READ]
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


def _session_payload(session: AgentSession) -> dict[str, Any]:
    payload = asdict(session)
    payload.pop("worker_session_id", None)
    return payload


async def api_sessions(request: Request) -> Response:
    """Return durable public agent sessions bound to one machine."""
    try:
        machine = _machine_arg(request.query_params.get("machine"))
        _require_scopes(machine)
        if machine != "local":
            require_remote_machine(machine)
        sessions = await asyncio.to_thread(
            get_tool_session_store().list_sessions
        )
        rows = [
            _session_payload(session)
            for session in sessions
            if _belongs_to_machine(session, machine)
        ][:UI_SESSION_MAX_ENTRIES]
        return _json_ok(
            {
                "machine": machine,
                "remote": machine != "local",
                "sessions": rows,
                "count": len(rows),
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
