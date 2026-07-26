"""Persist revisioned todo lists inside their owning session directory."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..config.settings import get_settings
from ..persistence import get_state_store
from ..schemas.result_models.todo import (
    ReadTodosOutput,
    TodoItem,
    WriteTodosOutput,
)
from ..tool_session.store import (
    SESSION_METADATA_MAX_BYTES,
    UnknownAgentSessionError,
    get_tool_session_store,
)


class TodoConflictError(RuntimeError):
    """Raised when a revision-guarded replacement targets stale todo state."""


def _todo_path(session_id: str) -> Path:
    """Return the canonical todo path colocated with one durable session."""
    return get_state_store().layout.session_todos_path(session_id)


def _session_transaction_path(session_id: str) -> Path:
    """Return the transaction identity shared by all state for one session."""
    return get_state_store().layout.session_transaction_path(session_id)


def _require_session_metadata(session_id: str) -> None:
    """Reject a session deleted after an earlier touch or inventory read."""
    store = get_state_store()
    value = store.read_json(
        store.layout.session_metadata_path(session_id),
        max_bytes=SESSION_METADATA_MAX_BYTES,
    )
    if value is None:
        raise UnknownAgentSessionError(
            f"unknown session_id {session_id!r}; call session_start first"
        )


def _read_todo_path(path: Path) -> ReadTodosOutput:
    """Read one revisioned todo file or return an empty initial state."""
    value = get_state_store().read_json(
        path, max_bytes=get_settings().max_todo_bytes
    )
    if value is None:
        return ReadTodosOutput(revision=0, todos=[])
    return ReadTodosOutput.model_validate(value)


def read_todos_execute(session_id: str) -> ReadTodosOutput:
    """Read the persisted todo list owned by one explicit agent session."""
    get_tool_session_store().touch_session(session_id)
    store = get_state_store()
    with store.transaction(_session_transaction_path(session_id)):
        _require_session_metadata(session_id)
        return _read_todo_path(_todo_path(session_id))


def todo_counts_execute() -> dict[str, int]:
    """Aggregate todo counts across durable local sessions without touching them."""
    total = 0
    open_count = 0
    store = get_state_store()
    for session in get_tool_session_store().list_sessions():
        if session.target != "local":
            continue
        with store.transaction(_session_transaction_path(session.session_id)):
            if (
                store.read_json(
                    store.layout.session_metadata_path(session.session_id),
                    max_bytes=SESSION_METADATA_MAX_BYTES,
                )
                is None
            ):
                continue
            result = _read_todo_path(_todo_path(session.session_id))
            total += len(result.todos)
            open_count += sum(
                item.status != "completed" for item in result.todos
            )
    return {"total": total, "open": open_count}


def _normalized_todos(todos: list[dict[str, Any]]) -> list[TodoItem]:
    settings = get_settings()
    if len(todos) > settings.max_todos:
        raise ValueError(
            f"Refusing to write {len(todos)} todos; max is {settings.max_todos}"
        )
    normalized: list[TodoItem] = []
    for idx, item in enumerate(todos):
        normalized.append(
            TodoItem(
                id=str(item.get("id") or idx + 1),
                content=str(item.get("content") or ""),
                status=str(item.get("status") or "pending"),
                priority=str(item.get("priority") or "medium"),
            )
        )
    return normalized


def write_todos_execute(
    todos: list[dict[str, Any]],
    session_id: str,
    expected_revision: int | None = None,
) -> WriteTodosOutput:
    """Normalize and atomically replace one explicit session's todo list."""
    get_tool_session_store().touch_session(session_id)
    if expected_revision is not None and (
        isinstance(expected_revision, bool) or expected_revision < 0
    ):
        raise ValueError("expected_revision must be a non-negative integer")

    normalized = _normalized_todos(todos)
    settings = get_settings()
    store = get_state_store()
    path = _todo_path(session_id)
    with store.transaction(_session_transaction_path(session_id)):
        _require_session_metadata(session_id)
        current = _read_todo_path(path)
        if (
            expected_revision is not None
            and expected_revision != current.revision
        ):
            raise TodoConflictError(
                "Todo list changed from revision "
                f"{expected_revision} to {current.revision}; reload before saving"
            )
        payload = WriteTodosOutput(
            revision=current.revision + 1,
            updated_at=time.time(),
            todos=normalized,
        )
        data = payload.model_dump(mode="json")
        encoded = json.dumps(
            data,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        encoded_bytes = len(encoded.encode("utf-8"))
        if encoded_bytes > settings.max_todo_bytes:
            raise ValueError(
                f"Refusing to write {encoded_bytes} todo bytes; max is {settings.max_todo_bytes}"
            )
        store.write_json(path, data)
        return payload
