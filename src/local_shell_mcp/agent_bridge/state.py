"""Manifest loading and configuration fingerprinting for the agent bridge."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from pydantic import ValidationError

from .models import AgentBridgeManifest, LoadedAgentManifest


def agent_config_fingerprint(config_dir: Path) -> str:
    """Return a stable content fingerprint for the injected agent config tree."""

    root = Path(config_dir)
    digest = hashlib.sha256()

    def update(*parts: object) -> None:
        for part in parts:
            digest.update(str(part).encode("utf-8", errors="replace"))
            digest.update(b"\0")

    def relative_path(path: Path) -> str:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return str(path)

    def update_path(path: Path, relative: str) -> None:
        try:
            file_stat = path.lstat()
        except OSError as exc:
            update(relative, "stat_error", type(exc).__name__, exc)
            return

        mode = file_stat.st_mode
        update(
            relative,
            stat.S_IFMT(mode),
            file_stat.st_size,
            file_stat.st_mtime_ns,
        )
        if stat.S_ISLNK(mode):
            try:
                update("link", os.readlink(path))
            except OSError as exc:
                update("link_error", type(exc).__name__, exc)
            return
        if not stat.S_ISREG(mode):
            return

        try:
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
        except OSError as exc:
            update("read_error", type(exc).__name__, exc)

    update_path(root, ".")
    try:
        root_stat = root.lstat()
    except OSError:
        return digest.hexdigest()
    if not stat.S_ISDIR(root_stat.st_mode):
        return digest.hexdigest()

    walk_errors: list[OSError] = []

    def on_walk_error(exc: OSError) -> None:
        walk_errors.append(exc)

    for current, dirnames, filenames in os.walk(
        root, topdown=True, onerror=on_walk_error
    ):
        dirnames.sort()
        filenames.sort()
        current_path = Path(current)

        for dirname in list(dirnames):
            child = current_path / dirname
            update_path(child, relative_path(child))
            try:
                if child.is_symlink():
                    dirnames.remove(dirname)
            except OSError:
                dirnames.remove(dirname)

        for filename in filenames:
            child = current_path / filename
            update_path(child, relative_path(child))

    for error in walk_errors:
        update("walk_error", type(error).__name__, error)

    return digest.hexdigest()


def load_agent_manifest(config_dir: Path) -> LoadedAgentManifest:
    """Read and validate the bridge manifest while preserving structured errors for status reporting."""
    config_path = config_dir / "config.json"
    if not config_path.exists():
        return LoadedAgentManifest(
            config_path=config_path, status="missing_config"
        )
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        data = AgentBridgeManifest.model_validate(raw)
    except ValidationError as exc:
        return LoadedAgentManifest(
            config_path=config_path,
            status="invalid_config",
            errors=[str(error) for error in exc.errors(include_input=False)],
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return LoadedAgentManifest(
            config_path=config_path,
            status="invalid_config",
            errors=[str(exc)],
        )
    return LoadedAgentManifest(
        config_path=config_path, status="loaded", data=data
    )
