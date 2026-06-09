from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

SENSITIVE_KEY_RE = re.compile(r"(authorization|api[_-]?key|token|secret|password|passwd)", re.I)


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
        return [redact_mapping(item) for item in value]
    return value


def load_agent_manifest(config_dir: Path) -> LoadedAgentManifest:
    config_path = config_dir / "config.json"
    if not config_path.exists():
        return LoadedAgentManifest(config_path=config_path, status="missing_config")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        data = AgentBridgeManifest.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        return LoadedAgentManifest(
            config_path=config_path,
            status="invalid_config",
            errors=[str(exc)],
        )
    return LoadedAgentManifest(config_path=config_path, status="loaded", data=data)
