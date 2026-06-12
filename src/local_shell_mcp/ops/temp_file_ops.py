"""Temporary file helpers shared by operation implementations."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from .path_ops import assert_text_input_size, prune_temp_dir, temp_dir


async def write_temp_text_file(
    input_name: str, content: str, filename_prefix: str, suffix: str
) -> Path:
    """Validate and write text content to a unique file in the managed temp directory."""
    assert_text_input_size(input_name, content)
    await asyncio.to_thread(prune_temp_dir)
    path = temp_dir() / f"{filename_prefix}-{uuid.uuid4().hex}.{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_text, content, encoding="utf-8")
    return path
