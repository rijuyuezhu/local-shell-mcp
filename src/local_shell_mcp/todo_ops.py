from __future__ import annotations

import json
import time
from pathlib import Path

from .settings import get_settings


def _todo_path() -> Path:
    path = get_settings().state_dir / "todos.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def todo_read() -> dict:
    path = _todo_path()
    if not path.exists():
        return {"todos": []}
    return json.loads(path.read_text(encoding="utf-8"))


def todo_write(todos: list[dict]) -> dict:
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
    _todo_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
