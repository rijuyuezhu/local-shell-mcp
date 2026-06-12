"""Python script execution helpers built on bounded shell command execution."""

from __future__ import annotations

import asyncio
import shlex
import uuid

from .command_ops import public_run_shell_timeout, run_shell
from .path_ops import (
    assert_text_input_size,
    prune_temp_dir,
    relative_display,
    temp_dir,
)


async def run_python_script(
    code: str, cwd: str = ".", timeout_s: int = 60
) -> dict:
    """Execute provided Python code from a temporary file."""
    assert_text_input_size("Python script", code)
    await asyncio.to_thread(prune_temp_dir)
    path = temp_dir() / f"script-{uuid.uuid4().hex}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_text, code, encoding="utf-8")
    result = await run_shell(
        f"python3 {shlex.quote(str(path))}",
        cwd=cwd,
        timeout_s=public_run_shell_timeout(timeout_s),
        max_output_bytes=1_000_000,
    )
    return {**result.model_dump(), "script_path": relative_display(path)}
