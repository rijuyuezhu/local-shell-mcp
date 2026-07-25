"""Persist agent-visible todo lists as revisioned JSON in the server state directory."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from ..config.settings import get_settings
from ..schemas.result_models.todo import (
    ReadTodosOutput,
    TodoItem,
    WriteTodosOutput,
)
from ..tool_session.store import get_tool_session_store
from ..utils.path_locks import path_lock


class TodoConflictError(RuntimeError):
    """Raised when a revision-guarded replacement targets stale todo state."""


def _todo_path(session_id: str | None = None) -> Path:
    """Return the state-file path used to persist a todo list."""
    state_dir = get_settings().state_dir
    if session_id is None:
        path = state_dir / "todos.json"
    else:
        path = state_dir / "todos" / f"{session_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_todo_path(path: Path) -> ReadTodosOutput:
    """Read one todo file, accepting pre-revision payloads as revision zero."""
    if not path.exists():
        return ReadTodosOutput(revision=0, todos=[])
    settings = get_settings()
    size = path.stat().st_size
    if size > settings.max_todo_bytes:
        raise ValueError(
            f"Refusing to read {size} todo bytes; max is {settings.max_todo_bytes}"
        )
    return ReadTodosOutput.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


def read_todos_execute(session_id: str | None = None) -> ReadTodosOutput:
    """Read the persisted todo list for one agent session."""
    if session_id is not None:
        get_tool_session_store().touch_session(session_id)
    return _read_todo_path(_todo_path(session_id))


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


def _atomic_write(path: Path, content: str) -> None:
    """Atomically replace one todo file with owner-only temporary storage."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            with contextlib.suppress(OSError):
                os.chmod(temporary, 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)


def write_todos_execute(
    todos: list[dict[str, Any]],
    session_id: str | None = None,
    expected_revision: int | None = None,
) -> WriteTodosOutput:
    """Normalize and atomically replace one session's todo list."""
    if session_id is not None:
        get_tool_session_store().touch_session(session_id)
    if expected_revision is not None and (
        isinstance(expected_revision, bool) or expected_revision < 0
    ):
        raise ValueError("expected_revision must be a non-negative integer")

    normalized = _normalized_todos(todos)
    settings = get_settings()
    path = _todo_path(session_id)
    with path_lock(path):
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
        encoded = json.dumps(
            payload.model_dump(mode="json"), ensure_ascii=False, indent=2
        )
        encoded_bytes = len(encoded.encode("utf-8"))
        if encoded_bytes > settings.max_todo_bytes:
            raise ValueError(
                f"Refusing to write {encoded_bytes} todo bytes; max is {settings.max_todo_bytes}"
            )
        _atomic_write(path, encoded)
        return payload
