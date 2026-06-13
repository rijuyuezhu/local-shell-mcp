"""Apply patch operations through bounded shell execution."""

import shlex

from .command_ops import run_shell
from .path_ops import relative_display
from .temp_file_ops import write_temp_text_file


async def apply_patch_text(patch: str, cwd: str = ".") -> dict:
    """Apply a unified diff through git apply and return the command result envelope."""
    patch_path = await write_temp_text_file("patch", patch, "patch", "diff")
    quoted = shlex.quote(str(patch_path))
    result = await run_shell(
        f"git apply --check {quoted} && git apply {quoted}",
        cwd=cwd,
        timeout_s=60,
        max_output_bytes=500_000,
    )
    return {**result.model_dump(), "patch_path": relative_display(patch_path)}
