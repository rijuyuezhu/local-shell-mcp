"""Workspace path, temporary-file, and text-size helpers."""

import os
import time
from pathlib import Path
from typing import Any

from ...app_paths import app_paths, ensure_private_directory
from ...config.settings import get_settings
from ...errors import PathNotFoundError


def workspace_root() -> Path:
    """Return the normalized workspace root used as the default filesystem boundary."""
    return get_settings().workspace_root.resolve()


def temp_dir() -> Path:
    """Create and return the scratch directory used for generated temporary files."""
    paths = app_paths()
    ensure_private_directory(paths.runtime_dir)
    return ensure_private_directory(paths.temp_dir)


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


def resolve_path_with_policy(
    path: str | Path,
    *,
    workspace_root: Path,
    allow_full_control: bool,
    path_denylist: tuple[str, ...],
    must_exist: bool = False,
    allow_missing_parent: bool = True,
    follow_final_symlink: bool = True,
) -> Path:
    """Resolve a path from explicit workspace-boundary policy values."""
    root = workspace_root.resolve()
    raw = Path(os.path.expandvars(os.path.expanduser(str(path))))
    if not raw.is_absolute():
        raw = root / raw
    if follow_final_symlink:
        resolved = (
            Path(os.path.abspath(raw))
            if allow_full_control
            else raw.resolve(strict=False)
        )
    else:
        resolved_parent = raw.parent.resolve(strict=False)
        resolved = resolved_parent / raw.name if raw.name else resolved_parent
    if not allow_full_control:
        boundary = resolved if follow_final_symlink else resolved.parent
        try:
            boundary.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Path escapes workspace: {path}") from exc

    lower = str(resolved).lower()
    for denied in path_denylist:
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


def resolve_path(
    path: str | Path,
    *,
    must_exist: bool = False,
    allow_missing_parent: bool = True,
    follow_final_symlink: bool = True,
) -> Path:
    """Resolve a path using the ambient compatibility workspace policy."""
    settings = get_settings()
    return resolve_path_with_policy(
        path,
        workspace_root=settings.workspace_root,
        allow_full_control=settings.allow_full_control,
        path_denylist=tuple(settings.path_denylist),
        must_exist=must_exist,
        allow_missing_parent=allow_missing_parent,
        follow_final_symlink=follow_final_symlink,
    )


def relative_display_from_root(path: Path, root: Path) -> str:
    """Render a lexical API path relative to an explicit workspace root."""
    resolved_root = root.resolve()
    candidate = path if path.is_absolute() else resolved_root / path
    lexical = Path(os.path.abspath(candidate))
    try:
        return lexical.relative_to(resolved_root).as_posix()
    except ValueError:
        return lexical.as_posix()


def relative_display(path: Path) -> str:
    """Render a lexical API path with portable POSIX separators."""
    return relative_display_from_root(path, workspace_root())


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
