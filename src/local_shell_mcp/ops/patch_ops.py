"""Apply patch operations through bounded shell execution."""

from __future__ import annotations

import asyncio
import shlex
import uuid

from .fs_ops import (
    assert_text_input_size,
    prune_temp_dir,
    relative_display,
    temp_dir,
)
from .shell_ops import run_shell


async def apply_patch_text(patch: str, cwd: str = ".") -> dict:
    """Apply a unified diff through git apply and return the command result envelope."""
    assert_text_input_size("patch", patch)
    await asyncio.to_thread(prune_temp_dir)
    patch_path = temp_dir() / f"patch-{uuid.uuid4().hex}.diff"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(patch_path.write_text, patch, encoding="utf-8")
    quoted = shlex.quote(str(patch_path))
    result = await run_shell(
        f"git apply --check {quoted} && git apply {quoted}",
        cwd=cwd,
        timeout_s=60,
        max_output_bytes=500_000,
    )
    return {**result.model_dump(), "patch_path": relative_display(patch_path)}
