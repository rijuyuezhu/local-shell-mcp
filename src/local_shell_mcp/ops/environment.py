"""Environment-info operation helpers."""

from ..config.settings import get_settings, safe_settings_dump
from ..schemas.result_models.environment import EnvironmentInfoOutput
from ..schemas.result_models.shell import RunShellCommandOutput
from .shell import run_shell


async def environment_info_execute() -> EnvironmentInfoOutput:
    """Return safe settings and a small bounded environment probe."""
    settings = get_settings()
    result = await run_shell(
        "uname -a; echo '---'; id; echo '---'; pwd; echo '---'; python3 --version; git --version",
        cwd=".",
        timeout_s=10,
    )
    return EnvironmentInfoOutput(
        settings=safe_settings_dump(settings),
        probe=RunShellCommandOutput.model_validate(
            result.model_dump(mode="json")
        ),
    )
