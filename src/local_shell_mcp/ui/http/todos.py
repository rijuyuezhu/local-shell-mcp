"""Authenticated Human UI APIs for session-scoped local and remote Todos."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ...config.settings import get_settings
from ...oauth.core.context import MissingOAuthScopeError, require_oauth_scopes
from ...oauth.core.scopes import (
    SCOPE_REMOTE_USE,
    SCOPE_SHELL_READ,
    SCOPE_SHELL_WRITE,
)
from ...ops.todo import (
    TodoConflictError,
    read_todos_execute,
    write_todos_execute,
)
from ...ops.utils.remote_session import call_remote_session_tool
from ...remote.tool_specs import REMOTE_WORKER_ORIGIN_HUMAN_UI
from ...schemas.result_models.todo import ReadTodosOutput, WriteTodosOutput
from ...tool_session.store import AgentSession, get_tool_session_store
from .common import json_error as _json_error
from .common import require_remote_machine

UI_TODO_MACHINE_MAX_BYTES = 255
UI_TODO_ID_MAX_BYTES = 256
UI_TODO_CONTENT_MAX_BYTES = 16_384
UI_TODO_LABEL_MAX_BYTES = 64
UI_TODO_SESSION_ID_BYTES = 8


def _json_ok(data: Any = None, message: str = "") -> JSONResponse:
    return JSONResponse({"ok": True, "message": message, "data": data})


def _require_scopes(*required: str) -> None:
    try:
        require_oauth_scopes(tuple(required))
    except MissingOAuthScopeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _machine_arg(value: Any) -> str:
    machine = str(value or "local").strip() or "local"
    if len(machine.encode("utf-8")) > UI_TODO_MACHINE_MAX_BYTES:
        raise ValueError(
            f"machine exceeds {UI_TODO_MACHINE_MAX_BYTES} encoded bytes"
        )
    return machine


def _session_id_arg(value: Any) -> str:
    session_id = str(value or "").strip()
    if (
        len(session_id.encode("ascii", errors="ignore"))
        != UI_TODO_SESSION_ID_BYTES
    ):
        raise ValueError("session_id must be an 8-character alphanumeric id")
    if not session_id.isascii() or not session_id.isalnum():
        raise ValueError("session_id must be an 8-character alphanumeric id")
    return session_id


def _require_todo_scopes(machine: str, *, write: bool = False) -> None:
    required = [SCOPE_SHELL_READ]
    if write:
        required.append(SCOPE_SHELL_WRITE)
    if machine != "local":
        required.append(SCOPE_REMOTE_USE)
    _require_scopes(*required)


def _session_for_machine(machine: str, session_id: str) -> AgentSession:
    session = get_tool_session_store().require_session(session_id)
    if machine == "local":
        if session.target != "local":
            raise ValueError(
                f"session {session_id} belongs to remote machine {session.machine}"
            )
        return session
    require_remote_machine(machine)
    if session.target != "remote" or session.machine != machine:
        raise ValueError(
            f"session {session_id} does not belong to machine {machine}"
        )
    return session


def _bounded_text(
    value: Any,
    *,
    field: str,
    max_bytes: int,
    default: str,
    allow_empty: bool = True,
) -> str:
    normalized = str(value if value is not None else default)
    if not normalized and not allow_empty:
        raise ValueError(f"{field} must not be empty")
    if len(normalized.encode("utf-8")) > max_bytes:
        raise ValueError(f"{field} exceeds {max_bytes} encoded bytes")
    return normalized


def _todo_items(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError("todos must be a JSON array")
    settings = get_settings()
    if len(value) > settings.max_todos:
        raise ValueError(
            f"Refusing to write {len(value)} todos; max is {settings.max_todos}"
        )
    normalized: list[dict[str, str]] = []
    identifiers: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"todos[{index}] must be a JSON object")
        identifier = _bounded_text(
            item.get("id"),
            field=f"todos[{index}].id",
            max_bytes=UI_TODO_ID_MAX_BYTES,
            default=str(index + 1),
            allow_empty=False,
        )
        if identifier in identifiers:
            raise ValueError(f"duplicate todo id: {identifier}")
        identifiers.add(identifier)
        normalized.append(
            {
                "id": identifier,
                "content": _bounded_text(
                    item.get("content"),
                    field=f"todos[{index}].content",
                    max_bytes=UI_TODO_CONTENT_MAX_BYTES,
                    default="",
                ),
                "status": _bounded_text(
                    item.get("status"),
                    field=f"todos[{index}].status",
                    max_bytes=UI_TODO_LABEL_MAX_BYTES,
                    default="pending",
                    allow_empty=False,
                ),
                "priority": _bounded_text(
                    item.get("priority"),
                    field=f"todos[{index}].priority",
                    max_bytes=UI_TODO_LABEL_MAX_BYTES,
                    default="medium",
                    allow_empty=False,
                ),
            }
        )
    return normalized


def _expected_revision(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("expected_revision must be a non-negative integer")
    return value


def _payload(
    machine: str,
    session: AgentSession,
    result: ReadTodosOutput,
) -> dict[str, Any]:
    settings = get_settings()
    return {
        "machine": machine,
        "remote": machine != "local",
        "session_id": session.session_id,
        "session": {
            "session_id": session.session_id,
            "target": session.target,
            "machine": session.machine,
            "workdir": session.workdir,
            "label": session.label,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "expires_at": session.expires_at,
        },
        **result.model_dump(mode="json"),
        "limits": {
            "todos": settings.max_todos,
            "bytes": settings.max_todo_bytes,
            "id_bytes": UI_TODO_ID_MAX_BYTES,
            "content_bytes": UI_TODO_CONTENT_MAX_BYTES,
            "label_bytes": UI_TODO_LABEL_MAX_BYTES,
        },
    }


async def _read(session: AgentSession) -> ReadTodosOutput:
    if session.target == "local":
        return await asyncio.to_thread(
            read_todos_execute,
            session.session_id,
            touch_session=False,
        )
    try:
        data = await call_remote_session_tool(
            session,
            "read_todos",
            {},
            audit_origin=REMOTE_WORKER_ORIGIN_HUMAN_UI,
        )
        return ReadTodosOutput.model_validate(data)
    except ValidationError as exc:
        raise RuntimeError(
            f"Remote machine {session.machine} returned malformed todo state"
        ) from exc


async def _write(
    session: AgentSession,
    todos: list[dict[str, str]],
    expected_revision: int,
) -> WriteTodosOutput:
    if session.target == "local":
        return await asyncio.to_thread(
            write_todos_execute,
            todos,
            session.session_id,
            expected_revision,
            touch_session=False,
        )
    try:
        data = await call_remote_session_tool(
            session,
            "write_todos",
            {
                "todos": todos,
                "expected_revision": expected_revision,
            },
            audit_origin=REMOTE_WORKER_ORIGIN_HUMAN_UI,
        )
        return WriteTodosOutput.model_validate(data)
    except ValidationError as exc:
        raise RuntimeError(
            f"Remote machine {session.machine} returned malformed todo state"
        ) from exc
    except RuntimeError as exc:
        message = str(exc)
        if (
            "TodoConflictError" in message
            or "Todo list changed from revision" in message
        ):
            raise TodoConflictError(
                message.removeprefix("TodoConflictError: ")
            ) from exc
        raise


async def api_todos(request: Request) -> Response:
    """Read or revision-guardedly replace one explicit session's todo list."""
    try:
        if request.method == "GET":
            machine = _machine_arg(request.query_params.get("machine"))
            session_id = _session_id_arg(request.query_params.get("session_id"))
            _require_todo_scopes(machine)
            session = _session_for_machine(machine, session_id)
            return _json_ok(_payload(machine, session, await _read(session)))

        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("request body must be a JSON object")
        machine = _machine_arg(body.get("machine"))
        session_id = _session_id_arg(body.get("session_id"))
        _require_todo_scopes(machine, write=True)
        session = _session_for_machine(machine, session_id)
        expected_revision = _expected_revision(body.get("expected_revision"))
        todos = _todo_items(body.get("todos"))
        return _json_ok(
            _payload(
                machine,
                session,
                await _write(session, todos, expected_revision),
            )
        )
    except HTTPException:
        raise
    except TodoConflictError as exc:
        return _json_error(exc, status_code=409)
    except ConnectionError as exc:
        return _json_error(exc, status_code=503)
    except RuntimeError as exc:
        return _json_error(exc, status_code=502)
    except Exception as exc:
        return _json_error(exc)
