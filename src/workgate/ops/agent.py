"""Agent Bridge operations shared by tools and source-only workers."""

from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from ..config.settings import get_settings
from ..schemas.result_models.agent import (
    ActivateAgentSkillOutput,
    AgentConfigStatusOutput,
    CallAgentMcpToolOutput,
    ListAgentMcpServersOutput,
    ListAgentMcpToolsOutput,
    ListAgentSkillsOutput,
    ReadAgentSkillFileOutput,
)
from ..tool_session.store import get_tool_session_store
from .utils.remote_session import call_remote_session_tool

if TYPE_CHECKING:
    from ..agent_bridge.models import AgentCapabilityRegistry, SkillRecord
    from ..agent_bridge.sources import SkillSource


def agent_registry(session_id: str | None = None) -> AgentCapabilityRegistry:
    """Build the complete local bridge registry, optionally for one local session."""
    from ..agent_bridge.mcp import AgentMcpClientManager
    from ..agent_bridge.service import build_agent_registry_from_settings

    return build_agent_registry_from_settings(
        client_manager_factory=AgentMcpClientManager,
        session_id=session_id,
    )


def _registry_or_default(
    registry: AgentCapabilityRegistry | None,
) -> AgentCapabilityRegistry:
    """Return an injected complete registry or build the default control registry."""
    return registry if registry is not None else agent_registry()


def _local_skill_registry(
    session_id: str | None,
) -> tuple[tuple[SkillSource, ...], dict[str, SkillRecord], list[str]]:
    """Scan ordered local Skill sources without importing the external MCP stack."""
    from ..agent_bridge.models import SkillScanResult
    from ..agent_bridge.sources import scan_skill_sources, skill_sources
    from ..agent_bridge.state import load_agent_manifest

    settings = get_settings()
    project_root = Path(settings.workspace_root)
    if session_id is not None:
        session = get_tool_session_store().touch_session(session_id)
        if session.target != "local":
            raise ValueError(
                "remote Skill registries must be dispatched to the worker"
            )
        project_root = Path(session.workdir)

    manifest = load_agent_manifest(settings.agent_config_dir)
    sources = skill_sources(
        project_root=project_root,
        managed_config_dir=settings.agent_config_dir,
        managed_directory=manifest.data.skills.directory,
    )
    scan = SkillScanResult()
    if manifest.status != "invalid_config" and manifest.data.skills.enabled:
        scan = scan_skill_sources(
            sources,
            max_skills=settings.max_skills,
            max_related_files=settings.max_skill_related_files,
            max_scan_entries=settings.max_skill_scan_entries,
            max_path_bytes=settings.max_skill_path_bytes,
            max_entry_bytes=settings.max_file_read_bytes,
        )
    return sources, scan.skills, scan.warnings


def _selected_skill_source(
    sources: tuple[SkillSource, ...], skill: SkillRecord
) -> SkillSource:
    """Return the exact source selected during the current bounded scan."""
    for source in sources:
        if (
            source.name == skill.source
            and str(source.path) == skill.source_path
        ):
            return source
    raise RuntimeError(f"Skill source is no longer available: {skill.source}")


def agent_config_status_execute(
    registry: AgentCapabilityRegistry | None = None,
) -> AgentConfigStatusOutput:
    """Return current agent bridge configuration status."""
    from ..agent_bridge.service import agent_config_status_payload

    return agent_config_status_payload(_registry_or_default(registry))


def list_agent_skills_execute(
    session_id: str | None = None,
    registry: AgentCapabilityRegistry | None = None,
) -> ListAgentSkillsOutput:
    """List Skills from ordered local sources for the optional session workdir."""
    if registry is not None:
        from ..agent_bridge.service import list_agent_skills_payload

        return list_agent_skills_payload(registry)
    sources, skills, warnings = _local_skill_registry(session_id)
    return ListAgentSkillsOutput(
        sources=[source.public_row() for source in sources],
        skills=[asdict(skill) for skill in skills.values()],
        warnings=warnings,
    )


async def list_agent_skills_dispatch_execute(
    session_id: str | None = None,
    registry: AgentCapabilityRegistry | None = None,
) -> ListAgentSkillsOutput:
    """List local or remote session Skill sources without crossing workspaces."""
    if session_id is None or registry is not None:
        return list_agent_skills_execute(session_id, registry)
    session = get_tool_session_store().touch_session(session_id)
    if session.target == "remote":
        data = await call_remote_session_tool(session, "list_agent_skills", {})
        return ListAgentSkillsOutput.model_validate(data)
    return list_agent_skills_execute(session_id)


def activate_agent_skill_execute(
    name: str,
    session_id: str | None = None,
    registry: AgentCapabilityRegistry | None = None,
) -> ActivateAgentSkillOutput:
    """Load one local Skill by exact name from the selected source priority."""
    if registry is not None:
        from ..agent_bridge.service import activate_agent_skill_payload

        return activate_agent_skill_payload(registry, name)
    from ..agent_bridge.skills import activate_skill

    sources, skills, _warnings = _local_skill_registry(session_id)
    skill = skills.get(name)
    if skill is None:
        raise ValueError(f"Unknown agent skill: {name}")
    source = _selected_skill_source(sources, skill)
    return ActivateAgentSkillOutput(
        **activate_skill(
            source.config_dir,
            skill,
            max_entry_bytes=get_settings().max_file_read_bytes,
        )
    )


async def activate_agent_skill_dispatch_execute(
    name: str,
    session_id: str | None = None,
    registry: AgentCapabilityRegistry | None = None,
) -> ActivateAgentSkillOutput:
    """Load one Skill locally or on the worker bound to a remote session."""
    if session_id is None or registry is not None:
        return activate_agent_skill_execute(name, session_id, registry)
    session = get_tool_session_store().touch_session(session_id)
    if session.target == "remote":
        data = await call_remote_session_tool(
            session, "activate_agent_skill", {"name": name}
        )
        return ActivateAgentSkillOutput.model_validate(data)
    return activate_agent_skill_execute(name, session_id)


def read_agent_skill_file_execute(
    name: str,
    path: str,
    session_id: str | None = None,
    registry: AgentCapabilityRegistry | None = None,
) -> ReadAgentSkillFileOutput:
    """Read one bounded local related file from the selected Skill source."""
    settings = get_settings()
    if registry is not None:
        from ..agent_bridge.service import read_agent_skill_file_payload

        return ReadAgentSkillFileOutput(
            **read_agent_skill_file_payload(
                registry,
                name,
                path,
                max_file_bytes=settings.max_file_read_bytes,
            )
        )
    from ..agent_bridge.skills import read_agent_skill_file

    sources, skills, _warnings = _local_skill_registry(session_id)
    skill = skills.get(name)
    if skill is None:
        raise ValueError(f"Unknown agent skill: {name}")
    source = _selected_skill_source(sources, skill)
    return ReadAgentSkillFileOutput(
        **read_agent_skill_file(
            source.config_dir,
            name,
            path,
            source.directory,
            source_name=source.name,
            source_path=str(source.path),
            max_file_bytes=settings.max_file_read_bytes,
        )
    )


async def read_agent_skill_file_dispatch_execute(
    name: str,
    path: str,
    session_id: str | None = None,
    registry: AgentCapabilityRegistry | None = None,
) -> ReadAgentSkillFileOutput:
    """Read a local or remote session Skill file through the owning runtime."""
    if session_id is None or registry is not None:
        return read_agent_skill_file_execute(name, path, session_id, registry)
    session = get_tool_session_store().touch_session(session_id)
    if session.target == "remote":
        data = await call_remote_session_tool(
            session,
            "read_agent_skill_file",
            {"name": name, "path": path},
        )
        return ReadAgentSkillFileOutput.model_validate(data)
    return read_agent_skill_file_execute(name, path, session_id)


def list_agent_mcp_servers_execute(
    registry: AgentCapabilityRegistry | None = None,
) -> ListAgentMcpServersOutput:
    """List configured agent MCP servers."""
    from ..agent_bridge.service import list_agent_mcp_servers_payload

    return list_agent_mcp_servers_payload(_registry_or_default(registry))


def list_agent_mcp_tools_execute(
    server: str | None = None,
    registry: AgentCapabilityRegistry | None = None,
) -> ListAgentMcpToolsOutput:
    """List tools exposed by configured agent MCP servers."""
    from ..agent_bridge.service import list_agent_mcp_tools_payload

    return list_agent_mcp_tools_payload(_registry_or_default(registry), server)


async def call_agent_mcp_tool_execute(
    server: str,
    tool: str,
    args: dict | None = None,
    registry: AgentCapabilityRegistry | None = None,
) -> CallAgentMcpToolOutput:
    """Call one tool on a configured agent MCP server."""
    from ..agent_bridge.service import call_agent_mcp_tool_payload

    return await call_agent_mcp_tool_payload(
        _registry_or_default(registry), server, tool, args or {}
    )
