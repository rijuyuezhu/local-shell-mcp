"""Persist the agent-visible todo list as JSON in the server state directory."""

import json
import time
from pathlib import Path

from ..config.settings import get_settings
from ..schemas.result_models.todo import ReadTodosOutput, WriteTodosOutput


def _todo_path() -> Path:
    """Return the state-file path used to persist the agent todo list."""
    path = get_settings().state_dir / "todos.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def read_todos_execute() -> ReadTodosOutput:
    """Read the persisted todo list, treating missing state as an empty list."""
    path = _todo_path()
    if not path.exists():
        return ReadTodosOutput(todos=[])
    settings = get_settings()
    size = path.stat().st_size
    if size > settings.max_todo_bytes:
        raise ValueError(
            f"Refusing to read {size} todo bytes; max is {settings.max_todo_bytes}"
        )
    return ReadTodosOutput.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


def write_todos_execute(todos: list[dict]) -> WriteTodosOutput:
    """Normalize todo entries and enforce count and byte limits before replacing persisted state."""
    settings = get_settings()
    if len(todos) > settings.max_todos:
        raise ValueError(
            f"Refusing to write {len(todos)} todos; max is {settings.max_todos}"
        )
    normalized = []
    for idx, item in enumerate(todos):
        normalized.append(
            {
                "id": str(item.get("id") or idx + 1),
                "content": str(item.get("content") or ""),
                "status": str(item.get("status") or "pending"),
                "priority": str(item.get("priority") or "medium"),
            }
        )
    payload = {"updated_at": time.time(), "todos": normalized}
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    encoded_bytes = len(encoded.encode("utf-8"))
    if encoded_bytes > settings.max_todo_bytes:
        raise ValueError(
            f"Refusing to write {encoded_bytes} todo bytes; max is {settings.max_todo_bytes}"
        )
    _todo_path().write_text(encoded, encoding="utf-8")
    return WriteTodosOutput.model_validate(payload)
