"""Build and serve the source/dependency bundle used by remote workers."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import re
import tarfile
from io import BytesIO
from pathlib import Path

from starlette.requests import Request
from starlette.responses import Response

from .constants import REMOTE_WORKER_DISTRIBUTIONS


def _canonical_dist_name(name: str) -> str:
    """Normalize distribution names so dependency bundles avoid duplicate tar entries."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _dist_name_from_requirement(requirement: str) -> str | None:
    """Extract the installable distribution name from a requirement string."""
    match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement)
    return match.group(1) if match else None


def _add_distribution_to_tar(
    tar: tarfile.TarFile, dist_name: str, seen: set[str]
) -> None:
    """Add a wheel-installed distribution and its importable files to the remote worker bundle."""
    canonical = _canonical_dist_name(dist_name)
    if canonical in seen:
        return
    seen.add(canonical)
    try:
        dist = importlib_metadata.distribution(dist_name)
    except importlib_metadata.PackageNotFoundError:
        return

    for requirement in dist.requires or []:
        required_name = _dist_name_from_requirement(requirement)
        if required_name:
            _add_distribution_to_tar(tar, required_name, seen)

    for entry in dist.files or []:
        entry_path = Path(str(entry))
        if entry_path.is_absolute() or ".." in entry_path.parts:
            continue
        source = Path(str(dist.locate_file(entry)))
        if not source.is_file() or source.suffix in {".pyc", ".pyo"}:
            continue
        tar.add(source, arcname=str(Path("vendor") / entry_path))


async def worker_bundle(request: Request) -> Response:
    """Serve a source-and-dependency bundle used to bootstrap a remote worker."""
    package_root = Path(__file__).resolve().parents[1]
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in package_root.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".sh"}:
                tar.add(
                    path,
                    arcname=str(path.relative_to(package_root.parent)),
                )
        seen: set[str] = set()
        for dist_name in REMOTE_WORKER_DISTRIBUTIONS:
            _add_distribution_to_tar(tar, dist_name, seen)
    return Response(buffer.getvalue(), media_type="application/gzip")
