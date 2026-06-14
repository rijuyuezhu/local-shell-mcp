"""Environment-info operation helpers."""

from ..config.settings import get_settings, safe_settings_dump
from .command_ops import run_shell


async def environment_info_execute() -> dict:
    """Return safe settings and a small bounded environment probe."""
    settings = get_settings()
    result = await run_shell(
        "uname -a; echo '---'; id; echo '---'; pwd; echo '---'; python3 --version; git --version",
        cwd=".",
        timeout_s=10,
    )
    return {
        "settings": safe_settings_dump(settings),
        "probe": result.model_dump(),
    }
