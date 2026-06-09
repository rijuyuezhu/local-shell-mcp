from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SENSITIVE_KEY_PATTERN = (
    r"(?:authorization|cookie|credentials?|api[_-]?key|access[_-]?key|private[_-]?key|"
    r"token|secret|password|passwd)"
)
SENSITIVE_KEY_RE = re.compile(SENSITIVE_KEY_PATTERN, re.I)
SENSITIVE_ARG_RE = re.compile(
    rf"(?P<prefix>--?[A-Za-z0-9_.-]*{SENSITIVE_KEY_PATTERN}[A-Za-z0-9_.-]*=)\S+",
    re.I,
)
SENSITIVE_SPACED_ARG_RE = re.compile(
    rf"(?P<prefix>(?:^|\s)--?[A-Za-z0-9_.-]*{SENSITIVE_KEY_PATTERN}"
    rf"[A-Za-z0-9_.-]*\s+)\S+",
    re.I,
)
SENSITIVE_FLAG_RE = re.compile(
    rf"^--?[A-Za-z0-9_.-]*{SENSITIVE_KEY_PATTERN}[A-Za-z0-9_.-]*$",
    re.I,
)


class AgentMcpServerConfig(BaseModel):
    type: Literal["stdio", "http", "sse"]
    enabled: bool = True
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("command")
    @classmethod
    def non_empty_command(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("command must not be empty")
        return value

    @field_validator("url")
    @classmethod
    def non_empty_url(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("url must not be empty")
        return value


class AgentSkillsConfig(BaseModel):
    enabled: bool = True
    directory: str = "skills"


class AgentDynamicToolsConfig(BaseModel):
    mcp: bool = True
    skills: bool = True


class AgentBridgeManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: int = 1
    mcp_servers: dict[str, AgentMcpServerConfig] = Field(
        default_factory=dict, alias="mcpServers"
    )
    skills: AgentSkillsConfig = Field(default_factory=AgentSkillsConfig)
    dynamic_tools: AgentDynamicToolsConfig = Field(
        default_factory=AgentDynamicToolsConfig, alias="dynamicTools"
    )

    @field_validator("version")
    @classmethod
    def supported_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("version must be 1")
        return value


@dataclass(frozen=True)
class LoadedAgentManifest:
    config_path: Path
    status: Literal["missing_config", "invalid_config", "loaded"]
    data: AgentBridgeManifest = field(default_factory=AgentBridgeManifest)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkillRecord:
    name: str
    entry_path: str
    description: str
    related_files: list[str]


@dataclass(frozen=True)
class SkillScanResult:
    skills: dict[str, SkillRecord] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _relative_posix(base: Path, path: Path) -> str:
    return path.resolve().relative_to(base.resolve()).as_posix()


def _first_sentence(value: str) -> str:
    match = re.match(r"(.+?[.!?])(?:\s|$)", value)
    if match:
        return match.group(1)
    return value


def _skill_description(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        key, separator, value = stripped.partition(":")
        if separator and key.strip().lower() == "description":
            return value.strip().strip("'\"") or "Agent skill"

    in_front_matter = False
    front_matter_possible = True
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if front_matter_possible and stripped in {"---", "+++"}:
            in_front_matter = True
            front_matter_possible = False
            continue
        if in_front_matter:
            if stripped in {"---", "...", "+++"}:
                in_front_matter = False
            continue
        front_matter_possible = False
        if stripped in {"---", "...", "+++"} or stripped.startswith("#"):
            continue
        return _first_sentence(stripped)
    return "Agent skill"


def scan_agent_skills(config_dir: Path, directory: str = "skills") -> SkillScanResult:
    skills_dir = (config_dir / directory).resolve()
    if not skills_dir.exists():
        return SkillScanResult(warnings=[f"Skills directory not found: {directory}"])

    skills: dict[str, SkillRecord] = {}
    warnings: list[str] = []
    for child in sorted(
        (candidate for candidate in skills_dir.iterdir() if candidate.is_dir()),
        key=lambda candidate: candidate.name,
    ):
        entry_path = child / "SKILL.md"
        if not entry_path.is_file():
            warnings.append(f"Skipping skill {child.name}: missing SKILL.md")
            continue
        markdown = entry_path.read_text(encoding="utf-8", errors="replace")
        related_files = sorted(
            _relative_posix(config_dir, related_path)
            for related_path in child.rglob("*")
            if related_path.is_file()
        )
        skills[child.name] = SkillRecord(
            name=child.name,
            entry_path=_relative_posix(config_dir, entry_path),
            description=_skill_description(markdown),
            related_files=related_files,
        )
    return SkillScanResult(skills=skills, warnings=warnings)


def activate_skill(config_dir: Path, skill: SkillRecord) -> dict[str, Any]:
    content = (config_dir / skill.entry_path).read_text(
        encoding="utf-8", errors="replace"
    )
    return {
        "name": skill.name,
        "entry_path": skill.entry_path,
        "description": skill.description,
        "content": content,
        "related_files": list(skill.related_files),
    }


def _sanitize_name(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", value).strip("_").lower()
    return sanitized or "unnamed"


def make_unique_tool_name(prefix: str, raw_name: str, seen: set[str]) -> str:
    base_name = _sanitize_name(f"{prefix}__{raw_name}")
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


def redact_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            if SENSITIVE_KEY_RE.search(str(key)):
                result[str(key)] = "<redacted>"
            else:
                result[str(key)] = redact_mapping(child)
        return result
    if isinstance(value, list):
        list_result: list[Any] = []
        redact_next = False
        for item in value:
            if redact_next:
                list_result.append("<redacted>")
                redact_next = False
                continue
            list_result.append(redact_mapping(item))
            if isinstance(item, str) and SENSITIVE_FLAG_RE.fullmatch(item):
                redact_next = True
        return list_result
    if isinstance(value, str):
        redacted = SENSITIVE_ARG_RE.sub(r"\g<prefix><redacted>", value)
        return SENSITIVE_SPACED_ARG_RE.sub(r"\g<prefix><redacted>", redacted)
    return value


def load_agent_manifest(config_dir: Path) -> LoadedAgentManifest:
    config_path = config_dir / "config.json"
    if not config_path.exists():
        return LoadedAgentManifest(config_path=config_path, status="missing_config")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        data = AgentBridgeManifest.model_validate(raw)
    except ValidationError as exc:
        return LoadedAgentManifest(
            config_path=config_path,
            status="invalid_config",
            errors=[str(error) for error in exc.errors(include_input=False)],
        )
    except (OSError, json.JSONDecodeError) as exc:
        return LoadedAgentManifest(
            config_path=config_path,
            status="invalid_config",
            errors=[str(exc)],
        )
    return LoadedAgentManifest(config_path=config_path, status="loaded", data=data)
