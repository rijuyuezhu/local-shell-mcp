"""Build and serve the Python-only source bundle used by remote workers."""

import fnmatch
import tarfile
from collections.abc import Iterable
from io import BytesIO
from pathlib import Path

from starlette.requests import Request
from starlette.responses import Response

# Keep the worker bundle Python-only and source-only. These patterns are a
# worker-runtime manifest, not a general local_shell_mcp package snapshot.
_WORKER_BUNDLE_INCLUDE_PATTERNS = (
    "__init__.py",
    "audit.py",
    "agent_bridge/__init__.py",
    "agent_bridge/redaction.py",
    "config/*.py",
    "ops/__init__.py",
    "ops/files.py",
    "ops/jobs.py",
    "ops/read.py",
    "ops/search.py",
    "ops/secret_scan.py",
    "ops/session.py",
    "ops/shell.py",
    "ops/transfer.py",
    "ops/utils/*.py",
    "remote/__init__.py",
    "remote/constants.py",
    "remote/tool_specs.py",
    "remote_worker/*.py",
    "remote_worker/**/*.py",
    "schemas/__init__.py",
    "schemas/input_models/__init__.py",
    "schemas/input_models/files.py",
    "schemas/result_models/*.py",
    "tool_session/*.py",
    "utils/__init__.py",
    "utils/serialization.py",
)
_WORKER_BUNDLE_EXCLUDE_PATTERNS = (
    "**/__pycache__/**",
    "**/*.pyc",
    "**/*.pyo",
)


def _matches_any(path: str, patterns: Iterable[str]) -> bool:
    """Return whether a POSIX relative path matches any manifest pattern."""
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _should_include_worker_file(path: Path, package_root: Path) -> bool:
    """Return whether one package file belongs in the worker bundle."""
    if path.suffix != ".py" or not path.is_file():
        return False
    relative = path.relative_to(package_root).as_posix()
    if _matches_any(relative, _WORKER_BUNDLE_EXCLUDE_PATTERNS):
        return False
    return _matches_any(relative, _WORKER_BUNDLE_INCLUDE_PATTERNS)


def _worker_bundle_paths(package_root: Path) -> list[Path]:
    """Return Python files selected by the worker-runtime manifest."""
    return sorted(
        path
        for path in package_root.rglob("*.py")
        if _should_include_worker_file(path, package_root)
    )


async def worker_bundle(request: Request) -> Response:
    """Serve a Python-only bundle used to bootstrap a remote worker."""
    package_root = Path(__file__).resolve().parents[1]
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in _worker_bundle_paths(package_root):
            tar.add(path, arcname=str(path.relative_to(package_root.parent)))
    return Response(buffer.getvalue(), media_type="application/gzip")
