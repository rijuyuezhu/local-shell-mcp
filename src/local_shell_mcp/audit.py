from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .settings import get_settings


def audit(event: str, **fields: Any) -> None:
    settings = get_settings()
    record = {
        "ts": time.time(),
        "event": event,
        **fields,
    }
    path: Path = settings.audit_log_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
