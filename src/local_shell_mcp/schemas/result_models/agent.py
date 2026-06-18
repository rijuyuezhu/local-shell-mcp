"""Typed structured outputs for agent bridge tools."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, RootModel


class AgentConfigStatusOutput(BaseModel):
    """Agent bridge configuration, skill, MCP server, and dynamic-tool status."""

    model_config = ConfigDict(extra="allow")
    """Allow passthrough keys for dynamically shaped output payloads."""

    config_dir: str = Field(description="Agent bridge configuration directory.")
    config_path: str = Field(description="Agent bridge manifest path.")
    manifest_status: str = Field(description="Manifest load status.")
    manifest_errors: list[str] = Field(
        description="Manifest validation or load errors."
    )
    skills: dict[str, Any] = Field(
        description="Skill discovery status summary."
    )
    mcp_servers: dict[str, Any] = Field(
        description="Configured upstream MCP server status rows."
    )
    dynamic_tools: dict[str, bool] = Field(
        description="Dynamic tool exposure flags."
    )


class ListAgentSkillsOutput(BaseModel):
    """Discovered agent skills."""

    skills: list[dict[str, Any]] = Field(
        description="Discovered skill metadata rows."
    )
    warnings: list[str] = Field(
        description="Non-fatal skill discovery warnings."
    )


class ActivateAgentSkillOutput(BaseModel):
    """Loaded agent skill instructions."""

    name: str = Field(description="Activated skill name.")
    entry_path: str = Field(
        description="Skill entry file path relative to the agent config directory."
    )
    description: str = Field(description="Skill summary description.")
    content: str = Field(
        description="Markdown instruction content for the skill."
    )
    related_files: list[str] = Field(description="Related skill file paths.")


class ListAgentMcpServersOutput(RootModel[dict[str, Any]]):
    """Configured agent MCP server status rows keyed by server name."""


class ListAgentMcpToolsOutput(BaseModel):
    """Tools exposed by configured agent MCP servers."""

    tools: list[dict[str, Any]] = Field(
        description="Redacted upstream MCP tool rows."
    )


class CallAgentMcpToolOutput(BaseModel):
    """Redacted result from an upstream agent MCP tool call."""

    model_config = ConfigDict(extra="allow")
    """Allow upstream tool result keys after redaction."""
