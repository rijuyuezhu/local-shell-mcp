from __future__ import annotations

import os
import sys

from .settings import get_settings

FROZEN_LOADER_ENV_VARS = (
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "DYLD_LIBRARY_PATH",
    "DYLD_INSERT_LIBRARIES",
)


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None))


def _restore_or_remove_loader_var(env: dict[str, str], name: str) -> None:
    original_name = f"{name}_ORIG"
    original_value = env.pop(original_name, None)
    if original_value:
        env[name] = original_value
    else:
        env.pop(name, None)


def subprocess_env() -> dict[str, str]:
    settings = get_settings()
    blocked = set(settings.shell_env_blocklist)
    prefixes = tuple(settings.shell_env_blocked_prefixes)
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in blocked and not key.startswith(prefixes)
    }
    if is_frozen_app():
        for name in FROZEN_LOADER_ENV_VARS:
            _restore_or_remove_loader_var(env, name)
    return env
