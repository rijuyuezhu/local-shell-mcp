"""Load agent bridge manifests, scan local skills, probe configured MCP servers, and assemble redacted dynamic tool registries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import queue
import re
import stat
import threading
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import (
    AgentBridgeManifest,
    AgentCapabilityRegistry,
    AgentMcpServerRecord,
    DynamicMcpToolRecord,
    DynamicSkillToolRecord,
    LoadedAgentManifest,
    SkillRecord,
    SkillScanResult,
)
from .models import (
    AgentDynamicToolsConfig as AgentDynamicToolsConfig,
)
from .models import (
    AgentMcpServerConfig as AgentMcpServerConfig,
)
from .models import (
    AgentSkillsConfig as AgentSkillsConfig,
)
from .redaction import (
    _redact_text as _redact_text,
)
from .redaction import (
    redact_configured_value_tree,
)
from .redaction import (
    redact_configured_values as redact_configured_values,
)
from .redaction import (
    redact_mapping as redact_mapping,
)


def _relative_posix(base: Path, path: Path) -> str:
    """Render a path relative to a base directory using POSIX separators for stable manifest output."""
    return path.resolve().relative_to(base.resolve()).as_posix()


def _is_relative_child_path(value: Path) -> bool:
    """Accept only relative child paths so skill manifests cannot reference arbitrary filesystem locations."""
    return not value.is_absolute() and ".." not in value.parts


def _first_sentence(value: str) -> str:
    """Extract the first prose sentence used as a compact skill or tool description."""
    match = re.match(r"(.+?[.!?])(?:\s|$)", value)
    if match:
        return match.group(1)
    return value


def _description_value(line: str) -> str | None:
    """Parse a front-matter description field from a Markdown skill file."""
    key, separator, value = line.strip().partition(":")
    if separator and key.strip().lower() == "description":
        return value.strip().strip("'\"") or "Agent skill"
    return None


def _skill_description(markdown: str) -> str:
    """Derive a human-readable skill description from front matter, heading text, or body prose."""
    lines = markdown.splitlines()
    line_index = 0
    while line_index < len(lines) and not lines[line_index].strip():
        line_index += 1

    if line_index < len(lines) and lines[line_index].strip() in {"---", "+++"}:
        delimiter = lines[line_index].strip()
        line_index += 1
        while line_index < len(lines):
            stripped = lines[line_index].strip()
            if stripped in {delimiter, "..."}:
                line_index += 1
                break
            description = _description_value(lines[line_index])
            if description is not None:
                return description
            line_index += 1

    in_code_fence = False
    for line in lines[line_index:]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        if stripped in {"---", "...", "+++"} or stripped.startswith("#"):
            continue
        return _first_sentence(stripped)
    return "Agent skill"


def scan_agent_skills(
    config_dir: Path, directory: str = "skills"
) -> SkillScanResult:
    """Discover valid Markdown skill files, resolve related files, and report unsafe or malformed entries as warnings."""
    try:
        config_root = config_dir.resolve()
    except (OSError, RuntimeError) as exc:
        return SkillScanResult(
            warnings=[f"Could not scan skills directory {directory}: {exc}"]
        )
    directory_path = Path(directory)
    if not _is_relative_child_path(directory_path):
        return SkillScanResult(
            warnings=[
                f"Skills directory must be inside config directory: {directory}"
            ]
        )

    try:
        skills_dir = (config_root / directory_path).resolve()
    except (OSError, RuntimeError) as exc:
        return SkillScanResult(
            warnings=[f"Could not scan skills directory {directory}: {exc}"]
        )
    if not skills_dir.is_relative_to(config_root):
        return SkillScanResult(
            warnings=[
                f"Skills directory must be inside config directory: {directory}"
            ]
        )
    try:
        skills_dir_exists = skills_dir.exists()
    except OSError as exc:
        return SkillScanResult(
            warnings=[f"Could not scan skills directory {directory}: {exc}"]
        )
    if not skills_dir_exists:
        return SkillScanResult(
            warnings=[f"Skills directory not found: {directory}"]
        )

    skills: dict[str, SkillRecord] = {}
    warnings: list[str] = []
    try:
        children = sorted(
            skills_dir.iterdir(), key=lambda candidate: candidate.name
        )
    except OSError as exc:
        return SkillScanResult(
            warnings=[f"Could not scan skills directory {directory}: {exc}"]
        )

    for child in children:
        try:
            if not child.is_dir():
                continue
            if child.is_symlink():
                warnings.append(
                    f"Skipping skill {child.name}: skill directory is a symlink"
                )
                continue
            skill_root = child.resolve()
            if not skill_root.is_relative_to(config_root):
                warnings.append(
                    f"Skipping skill {child.name}: skill directory must be inside config directory"
                )
                continue
            entry_path = child / "SKILL.md"
            if entry_path.is_symlink():
                warnings.append(
                    f"Skipping skill {child.name}: "
                    "SKILL.md must be a regular file inside the skill directory"
                )
                continue
            if not entry_path.is_file():
                warnings.append(
                    f"Skipping skill {child.name}: missing SKILL.md"
                )
                continue
            if not entry_path.resolve().is_relative_to(skill_root):
                warnings.append(
                    f"Skipping skill {child.name}: SKILL.md must be inside the skill directory"
                )
                continue
            markdown = entry_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            warnings.append(f"Skipping skill {child.name}: {exc}")
            continue

        related_files: list[str] = []
        try:
            for related_path in child.rglob("*"):
                try:
                    if not related_path.is_file():
                        continue
                    if (
                        related_path.is_symlink()
                        or not related_path.resolve().is_relative_to(skill_root)
                    ):
                        warnings.append(
                            f"Skipping related file "
                            f"{related_path.relative_to(config_root).as_posix()}: "
                            "file must be inside the skill directory"
                        )
                        continue
                    related_files.append(
                        _relative_posix(config_root, related_path)
                    )
                except OSError as exc:
                    try:
                        related_display = related_path.relative_to(
                            config_root
                        ).as_posix()
                    except ValueError:
                        related_display = str(related_path)
                    warnings.append(
                        f"Skipping related file {related_display}: {exc}"
                    )
        except OSError as exc:
            warnings.append(
                f"Skipping related files for skill {child.name}: {exc}"
            )

        skills[child.name] = SkillRecord(
            name=child.name,
            entry_path=_relative_posix(config_root, entry_path),
            description=_skill_description(markdown),
            related_files=sorted(related_files),
        )
    return SkillScanResult(skills=skills, warnings=warnings)


def activate_skill(config_dir: Path, skill: SkillRecord) -> dict[str, Any]:
    """Load a skill entry point and related files into a payload that an agent can use to execute the skill."""
    config_root = config_dir.resolve()
    entry_relative = Path(skill.entry_path)
    if not _is_relative_child_path(entry_relative):
        raise ValueError("Skill entry path must be inside config directory")
    entry_path = config_root / entry_relative
    skill_root = entry_path.parent.resolve()
    if entry_path.is_symlink() or not entry_path.is_file():
        raise ValueError("Skill entry path must be a regular file")
    entry_resolved = entry_path.resolve()
    if not entry_resolved.is_relative_to(config_root):
        raise ValueError("Skill entry path must be inside config directory")
    if not entry_resolved.is_relative_to(skill_root):
        raise ValueError("Skill entry path must be inside the skill directory")
    content = entry_path.read_text(encoding="utf-8", errors="replace")
    return {
        "name": skill.name,
        "entry_path": skill.entry_path,
        "description": skill.description,
        "content": content,
        "related_files": list(skill.related_files),
    }


def _sanitize_name(value: str) -> str:
    """Convert arbitrary server, skill, or tool names into safe lowercase fragments for generated tool names."""
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", value).strip("_").lower()
    return sanitized or "unnamed"


def make_unique_tool_name(prefix: str, raw_name: str, seen: set[str]) -> str:
    """Create a collision-free public tool name from a prefix and upstream name."""
    base_name = f"{_sanitize_name(prefix)}__{_sanitize_name(raw_name)}"
    candidate = base_name
    if candidate in seen:
        digest = hashlib.sha1(raw_name.encode("utf-8")).hexdigest()[:8]
        candidate = f"{base_name}__{digest}"
        counter = 2
        while candidate in seen:
            candidate = f"{base_name}__{digest}_{counter}"
            counter += 1
    seen.add(candidate)
    return candidate


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


def _run_async_blocking(coro: Any, timeout_s: float | None = None) -> Any:
    """Run an async probe from synchronous registry-building code with a bounded timeout."""
    if timeout_s is None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def run() -> None:
        try:
            result_queue.put((True, asyncio.run(coro)))
        except BaseException as exc:
            result_queue.put((False, exc))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        if timeout_s is None:
            success, result = result_queue.get()
        else:
            success, result = result_queue.get(timeout=timeout_s)
    except queue.Empty:
        raise TimeoutError(
            f"operation timed out after {timeout_s:g}s"
        ) from None
    if success:
        return result
    raise result


def _probe_timeout_seconds(probe_timeout_s: float) -> float:
    """Clamp the MCP probe timeout to a positive value before probing upstream servers."""
    return max(0.001, probe_timeout_s)


def build_agent_registry(
    config_dir: Path,
    client_manager: Any | None = None,
    probe_timeout_s: float = 5,
    dynamic_mcp_tools: bool | None = None,
    dynamic_skill_tools: bool | None = None,
) -> AgentCapabilityRegistry:
    """Build a complete bridge registry by loading config, scanning skills, probing MCP servers, and assigning dynamic names."""
    config_root = Path(config_dir)
    manifest = load_agent_manifest(config_root)
    probe_timeout = _probe_timeout_seconds(probe_timeout_s)
    if client_manager is None:
        from .mcp import AgentMcpClientManager

        client_manager = AgentMcpClientManager(call_timeout_s=probe_timeout)

    skill_scan = SkillScanResult()
    mcp_servers: dict[str, AgentMcpServerRecord] = {}
    if manifest.status == "loaded":
        if manifest.data.skills.enabled:
            skill_scan = scan_agent_skills(
                config_root, manifest.data.skills.directory
            )

        for name, server in manifest.data.mcp_servers.items():
            if not server.enabled:
                mcp_servers[name] = AgentMcpServerRecord(
                    name=name,
                    config=server,
                    available=False,
                    error="disabled",
                )
                continue

            try:
                tools = _run_async_blocking(
                    asyncio.wait_for(
                        client_manager.list_tools(name, server),
                        timeout=probe_timeout,
                    ),
                    timeout_s=probe_timeout,
                )
            except Exception as exc:
                mcp_servers[name] = AgentMcpServerRecord(
                    name=name,
                    config=server,
                    available=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
                continue

            mcp_servers[name] = AgentMcpServerRecord(
                name=name,
                config=server,
                available=True,
                tools=tools,
            )

    effective_dynamic_skills = (
        manifest.data.dynamic_tools.skills
        if dynamic_skill_tools is None
        else dynamic_skill_tools
    )
    effective_dynamic_mcp = (
        manifest.data.dynamic_tools.mcp
        if dynamic_mcp_tools is None
        else dynamic_mcp_tools
    )

    seen_names: set[str] = set()
    skill_tool_map: dict[str, DynamicSkillToolRecord] = {}
    if effective_dynamic_skills:
        for skill_name in skill_scan.skills:
            dynamic_name = make_unique_tool_name(
                "activate_skill", skill_name, seen_names
            )
            skill_tool_map[dynamic_name] = DynamicSkillToolRecord(
                dynamic_name, skill_name
            )

    mcp_tool_map: dict[str, DynamicMcpToolRecord] = {}
    if effective_dynamic_mcp:
        for server_name, record in mcp_servers.items():
            if not record.available:
                continue
            for tool in record.tools:
                display_server_name = str(
                    redact_configured_value_tree(
                        server_name,
                        record.config.env,
                        record.config.headers,
                    )
                )
                display_tool_name = str(
                    redact_configured_value_tree(
                        tool.name,
                        record.config.env,
                        record.config.headers,
                    )
                )
                dynamic_name = make_unique_tool_name(
                    f"agent_mcp__{display_server_name}",
                    display_tool_name,
                    seen_names,
                )
                mcp_tool_map[dynamic_name] = DynamicMcpToolRecord(
                    dynamic_name, server_name, tool.name
                )

    return AgentCapabilityRegistry(
        config_dir=config_root,
        config_path=manifest.config_path,
        manifest_status=manifest.status,
        manifest_errors=manifest.errors,
        skills=skill_scan.skills,
        skill_warnings=skill_scan.warnings,
        mcp_servers=mcp_servers,
        dynamic_mcp_tools=effective_dynamic_mcp,
        dynamic_skill_tools=effective_dynamic_skills,
        dynamic_skill_tool_map=skill_tool_map,
        dynamic_mcp_tool_map=mcp_tool_map,
        client_manager=client_manager,
    )
