"""Authenticated Human UI APIs for session-scoped local and remote Todos."""

from __future__ import annotations

import asyncio
import threading
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
from ...ops.utils.path import workspace_root
from ...schemas.result_models.todo import ReadTodosOutput, WriteTodosOutput
from ...tool_session.store import (
    UnknownAgentSessionError,
    get_tool_session_store,
)
from .common import json_error as _json_error
from .remote_files import call_remote_ui_workspace_tool

UI_TODO_MACHINE_MAX_BYTES = 255
UI_TODO_ID_MAX_BYTES = 256
UI_TODO_CONTENT_MAX_BYTES = 16_384
UI_TODO_LABEL_MAX_BYTES = 64

_LOCAL_SESSION_LOCK = threading.Lock()
_LOCAL_SESSION: tuple[str, str] | None = None


def clear_ui_todo_sessions() -> None:
    """Clear the cached local UI session. Intended for tests and process resets."""
    global _LOCAL_SESSION
    with _LOCAL_SESSION_LOCK:
        _LOCAL_SESSION = None


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


def _require_todo_scopes(machine: str, *, write: bool = False) -> None:
    required = [SCOPE_SHELL_READ]
    if write:
        required.append(SCOPE_SHELL_WRITE)
    if machine != "local":
        required.append(SCOPE_REMOTE_USE)
    _require_scopes(*required)


def _local_ui_session_id() -> str:
    """Return one reusable explicit local workspace session for Human UI state."""
    global _LOCAL_SESSION
    workdir = str(workspace_root())
    with _LOCAL_SESSION_LOCK:
        cached = _LOCAL_SESSION
        if cached is not None and cached[0] == workdir:
            try:
                session = get_tool_session_store().require_session(cached[1])
            except UnknownAgentSessionError:
                pass
            else:
                if session.target == "local" and session.workdir == workdir:
                    return session.session_id
        session = get_tool_session_store().create_session(
            target="local",
            workdir=workdir,
            label="Human UI Workspace",
        )
        _LOCAL_SESSION = (workdir, session.session_id)
        return session.session_id


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


def _payload(machine: str, result: ReadTodosOutput) -> dict[str, Any]:
    settings = get_settings()
    return {
        "machine": machine,
        "remote": machine != "local",
        **result.model_dump(mode="json"),
        "limits": {
            "todos": settings.max_todos,
            "bytes": settings.max_todo_bytes,
            "id_bytes": UI_TODO_ID_MAX_BYTES,
            "content_bytes": UI_TODO_CONTENT_MAX_BYTES,
            "label_bytes": UI_TODO_LABEL_MAX_BYTES,
        },
    }


async def _read(machine: str) -> ReadTodosOutput:
    if machine == "local":
        return await asyncio.to_thread(
            read_todos_execute, _local_ui_session_id()
        )
    try:
        data = await call_remote_ui_workspace_tool(machine, "read_todos", {})
        return ReadTodosOutput.model_validate(data)
    except ValidationError as exc:
        raise RuntimeError(
            f"Remote machine {machine} returned malformed todo state"
        ) from exc


async def _write(
    machine: str,
    todos: list[dict[str, str]],
    expected_revision: int,
) -> WriteTodosOutput:
    if machine == "local":
        return await asyncio.to_thread(
            write_todos_execute,
            todos,
            _local_ui_session_id(),
            expected_revision,
        )
    try:
        data = await call_remote_ui_workspace_tool(
            machine,
            "write_todos",
            {
                "todos": todos,
                "expected_revision": expected_revision,
            },
        )
        return WriteTodosOutput.model_validate(data)
    except ValidationError as exc:
        raise RuntimeError(
            f"Remote machine {machine} returned malformed todo state"
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
    """Read or revision-guardedly replace one machine's UI todo list."""
    try:
        if request.method == "GET":
            machine = _machine_arg(request.query_params.get("machine"))
            _require_todo_scopes(machine)
            return _json_ok(_payload(machine, await _read(machine)))

        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("request body must be a JSON object")
        machine = _machine_arg(body.get("machine"))
        _require_todo_scopes(machine, write=True)
        expected_revision = _expected_revision(body.get("expected_revision"))
        todos = _todo_items(body.get("todos"))
        return _json_ok(
            _payload(
                machine,
                await _write(machine, todos, expected_revision),
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
