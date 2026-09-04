"""Resolve system or explicitly configured tmux executables."""

import os
import shutil
from dataclasses import dataclass

from ..config.settings import get_settings


def tmux_env_overrides() -> dict[str, str]:
    """Detach project-owned tmux commands from any enclosing tmux client."""
    return {"TMUX": "", "TMUX_PANE": ""}


def detached_tmux_env() -> dict[str, str]:
    """Return the process environment without enclosing tmux client markers."""
    env = os.environ.copy()
    env.pop("TMUX", None)
    env.pop("TMUX_PANE", None)
    return env


@dataclass(frozen=True)
class TmuxSelection:
    """Describe the selected tmux executable and where it came from."""

    path: str | None
    """Resolved executable path, or None when no usable tmux exists."""

    source: str
    """Resolution source: system, configured, or unavailable."""

    configured: str
    """Normalized configuration value used for resolution."""


def resolve_tmux(configured: str | None = None) -> TmuxSelection:
    """Resolve tmux from explicit configuration or the system PATH."""
    value = configured
    if value is None:
        value = str(get_settings().tmux_bin)
    normalized = str(value or "tmux").strip() or "tmux"
    resolved = shutil.which(normalized)
    if resolved:
        source = "system" if normalized == "tmux" else "configured"
        return TmuxSelection(resolved, source, normalized)
    if normalized != "tmux":
        return TmuxSelection(None, "configured", normalized)
    return TmuxSelection(None, "unavailable", normalized)


def require_tmux(configured: str | None = None) -> TmuxSelection:
    """Resolve tmux or raise an actionable persistent-shell error."""
    selection = resolve_tmux(configured)
    if selection.path is not None:
        return selection
    if selection.source == "configured":
        raise RuntimeError(
            f"Configured tmux executable is unavailable: {selection.configured}"
        )
    raise RuntimeError(
        "tmux is unavailable; install tmux or configure LOCAL_SHELL_MCP_TMUX_BIN"
    )


def tmux_backend_info() -> dict[str, str | bool | None]:
    """Return non-sensitive diagnostics for the persistent-shell backend."""
    selection = resolve_tmux()
    return {
        "available": selection.path is not None,
        "source": selection.source,
        "path": selection.path,
    }
