"""Python script execution helpers built on bounded shell command execution."""

from __future__ import annotations

import shlex

from .command_ops import public_run_shell_timeout, run_shell
from .path_ops import relative_display
from .temp_file_ops import write_temp_text_file


async def run_python_script(
    code: str, cwd: str = ".", timeout_s: int = 60
) -> dict:
    """Execute provided Python code from a temporary file."""
    path = await write_temp_text_file("Python script", code, "script", "py")
    result = await run_shell(
        f"python3 {shlex.quote(str(path))}",
        cwd=cwd,
        timeout_s=public_run_shell_timeout(timeout_s),
        max_output_bytes=1_000_000,
    )
    return {**result.model_dump(), "script_path": relative_display(path)}
