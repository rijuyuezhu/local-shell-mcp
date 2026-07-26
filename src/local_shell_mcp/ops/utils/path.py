"""Workspace path, temporary-file, and text-size helpers."""

import os
import time
from pathlib import Path
from typing import Any

from ...config.settings import get_settings
from ...errors import PathNotFoundError
from ...persistence import get_state_store


def workspace_root() -> Path:
    """Return the normalized workspace root used as the default filesystem boundary."""
    return get_settings().workspace_root.resolve()


def temp_dir() -> Path:
    """Create and return the scratch directory used for generated temporary files."""
    path = get_state_store().layout.tmp_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def prune_temp_dir(*, minimum_age_s: float = 0.0) -> None:
    """Remove over-budget temporary files once they reach a minimum age."""
    settings = get_settings()
    path = temp_dir()
    try:
        files = [item for item in path.iterdir() if item.is_file()]
    except OSError:
        return

    entries: list[tuple[float, int, Path]] = []
    for item in files:
        try:
            stat = item.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime, stat.st_size, item))

    entries.sort(reverse=True)
    total_bytes = 0
    now = time.time()
    for index, (modified, size, item) in enumerate(entries):
        total_bytes += size
        if (
            index < settings.max_tmp_files
            and total_bytes <= settings.max_tmp_bytes
        ):
            continue
        if now - modified < max(0.0, minimum_age_s):
            continue
        try:
            item.unlink()
        except OSError:
            continue


def assert_text_input_size(
    label: str, text: str, limit: int | None = None
) -> None:
    """Reject oversized text payloads before writing or executing user-provided text."""
    settings = get_settings()
    max_bytes = limit or settings.max_file_write_bytes
    size = len(text.encode("utf-8"))
    if size > max_bytes:
        raise ValueError(
            f"Refusing {label} of {size} bytes; max is {max_bytes}"
        )


def resolve_path(
    path: str | Path,
    *,
    must_exist: bool = False,
    allow_missing_parent: bool = True,
    follow_final_symlink: bool = True,
) -> Path:
    """Resolve a path, optionally preserving the final directory entry.

    In normal mode, absolute paths outside workspace are rejected. In full-control mode,
    any absolute path inside the container is allowed.
    """
    settings = get_settings()
    root = settings.workspace_root.resolve()
    raw = Path(os.path.expandvars(os.path.expanduser(str(path))))
    if not raw.is_absolute():
        raw = root / raw
    if follow_final_symlink:
        resolved = (
            Path(os.path.abspath(raw))
            if settings.allow_full_control
            else raw.resolve(strict=False)
        )
    else:
        resolved_parent = raw.parent.resolve(strict=False)
        resolved = resolved_parent / raw.name if raw.name else resolved_parent
    if not settings.allow_full_control:
        boundary = resolved if follow_final_symlink else resolved.parent
        try:
            boundary.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Path escapes workspace: {path}") from exc

    lower = str(resolved).lower()
    for denied in settings.path_denylist:
        if denied and denied.lower() in lower:
            raise PermissionError(f"Path is denylisted: {path}")

    exists = (
        resolved.exists() if follow_final_symlink else os.path.lexists(resolved)
    )
    if must_exist and not exists:
        raise PathNotFoundError(resolved)
    if not allow_missing_parent and not resolved.parent.exists():
        raise PathNotFoundError(resolved.parent)
    return resolved


def relative_display(path: Path) -> str:
    """Render a lexical API path with portable POSIX separators."""
    root = workspace_root()
    candidate = path if path.is_absolute() else root / path
    lexical = Path(os.path.abspath(candidate))
    try:
        return lexical.relative_to(root).as_posix()
    except ValueError:
        return lexical.as_posix()


def missing_path_context(
    path: str | Path, *, max_entries: int = 50
) -> dict[str, Any]:
    """Describe the nearest existing parent and sibling entries for a missing path diagnostic."""
    resolved = resolve_path(path)
    nearest = next(
        (parent for parent in [resolved, *resolved.parents] if parent.exists()),
        None,
    )
    entries: list[str] = []
    truncated = False

    if nearest and nearest.is_dir():
        limit = max(0, max_entries)
        for child in nearest.iterdir():
            if child.name == ".git":
                continue
            if len(entries) >= limit:
                truncated = True
                break
            entries.append(f"{child.name}/" if child.is_dir() else child.name)

    return {
        "path": str(resolved),
        "exists": resolved.exists(),
        "nearest_existing_parent": str(nearest) if nearest else None,
        "nearest_parent_entries": entries,
        "truncated": truncated,
    }
