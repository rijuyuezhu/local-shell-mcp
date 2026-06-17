from __future__ import annotations

import importlib.metadata as importlib_metadata
import platform
import sys
from typing import Any

from . import __version__


def package_version() -> str:
    try:
        return importlib_metadata.version("local-shell-mcp")
    except importlib_metadata.PackageNotFoundError:
        return __version__


def version_info() -> dict[str, Any]:
    return {
        "version": __version__,
        "package_version": package_version(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "executable": sys.executable,
    }


def format_version_info(info: dict[str, Any] | None = None) -> str:
    data = version_info() if info is None else info
    if data.get("package_version") and data.get("package_version") != data.get("version"):
        return f"local-shell-mcp {data['version']} (package {data['package_version']})"
    return f"local-shell-mcp {data['version']}"
