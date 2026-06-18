"""Python script execution helpers built on bounded shell command execution."""

import shlex

from ..schemas.result_models.shell import RunPythonCodeOutput
from .command_ops import run_shell, run_shell_command_timeout
from .path_ops import relative_display
from .temp_file_ops import write_temp_text_file


async def run_python_code_execute(
    code: str, cwd: str = ".", timeout_s: int = 60
) -> RunPythonCodeOutput:
    """Execute provided Python code from a temporary file."""
    path = await write_temp_text_file("Python script", code, "script", "py")
    result = await run_shell(
        f"python3 {shlex.quote(str(path))}",
        cwd=cwd,
        timeout_s=run_shell_command_timeout(timeout_s),
        max_output_bytes=1_000_000,
    )
    return RunPythonCodeOutput.model_validate(
        {**result.model_dump(), "script_path": relative_display(path)}
    )
