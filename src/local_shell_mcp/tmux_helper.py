"""Resolve system, configured, or release-bundled tmux executables."""

from __future__ import annotations

import os
import platform
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from .config.settings import get_settings

TMUX_HELPER_VERSION = "3.5a"


@dataclass(frozen=True)
class TmuxSelection:
    """Describe the selected tmux executable and where it came from."""

    path: str | None
    """Resolved executable path, or None when no usable tmux exists."""

    source: str
    """Resolution source: system, configured, bundled, or unavailable."""

    configured: str
    """Normalized configuration value used for resolution."""


def _platform_tag(
    *, system: str | None = None, machine: str | None = None
) -> str | None:
    """Return the bundled-helper tag for one supported Linux platform."""
    normalized_system = (system or platform.system()).strip().lower()
    if normalized_system != "linux":
        return None
    normalized_machine = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86_64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }.get((machine or platform.machine()).strip().lower())
    if normalized_machine is None:
        return None
    return f"linux-{normalized_machine}"


def bundled_tmux_path(*, package_root: Path | None = None) -> Path | None:
    """Return an executable bundled tmux helper for this platform, if present."""
    tag = _platform_tag()
    if tag is None:
        return None
    root = package_root or Path(__file__).resolve().parent
    candidate = root / "helpers" / tag / "tmux"
    try:
        mode = candidate.lstat().st_mode
    except OSError:
        return None
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        return None
    if not os.access(candidate, os.X_OK):
        try:
            candidate.chmod(mode | stat.S_IXUSR)
        except OSError:
            return None
    return candidate if os.access(candidate, os.X_OK) else None


def resolve_tmux(
    configured: str | None = None, *, package_root: Path | None = None
) -> TmuxSelection:
    """Resolve tmux with explicit configuration and system installs first."""
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
    bundled = bundled_tmux_path(package_root=package_root)
    if bundled is not None:
        return TmuxSelection(str(bundled), "bundled", normalized)
    return TmuxSelection(None, "unavailable", normalized)


def require_tmux(
    configured: str | None = None, *, package_root: Path | None = None
) -> TmuxSelection:
    """Resolve tmux or raise an actionable persistent-shell error."""
    selection = resolve_tmux(configured, package_root=package_root)
    if selection.path is not None:
        return selection
    if selection.source == "configured":
        raise RuntimeError(
            f"Configured tmux executable is unavailable: {selection.configured}"
        )
    raise RuntimeError(
        "tmux is unavailable; install tmux or use a Linux standalone release "
        "that includes the bundled helper"
    )


def tmux_backend_info() -> dict[str, str | bool | None]:
    """Return non-sensitive diagnostics for the persistent-shell backend."""
    selection = resolve_tmux()
    return {
        "available": selection.path is not None,
        "source": selection.source,
        "path": selection.path,
        "bundled_version": (
            TMUX_HELPER_VERSION if selection.source == "bundled" else None
        ),
    }
