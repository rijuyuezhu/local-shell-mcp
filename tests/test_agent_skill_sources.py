from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import local_shell_mcp.ops.agent as agent_ops
from local_shell_mcp.agent_bridge.registry import build_agent_registry
from local_shell_mcp.agent_bridge.sources import (
    SkillSource,
    scan_skill_sources,
    skill_sources,
)
from local_shell_mcp.agent_bridge.state import agent_registry_fingerprint
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.remote_worker.dispatch import execute_worker_tool
from local_shell_mcp.tool_session.store import get_tool_session_store


class _NoopClientManager:
    async def list_tools(self, name: str, config: Any) -> list[Any]:  # noqa: ARG002
        return []


def _install_skill(root: Path, directory: str, name: str, marker: str) -> Path:
    skill = root / directory / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"# {name}\n\n{marker}.\n", encoding="utf-8"
    )
    (skill / "guide.md").write_text(marker, encoding="utf-8")
    return skill


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    *,
    workspace: Path,
    state_dir: Path,
    config_dir: Path,
    xdg_config_home: Path,
) -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state_dir))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config_home))
    clear_settings_cache()
    get_tool_session_store().clear()


def test_skill_sources_use_project_managed_global_order_and_ignore_relative_xdg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    managed = tmp_path / "managed"
    project.mkdir()
    managed.mkdir()
    absolute_xdg = tmp_path / "xdg"

    sources = skill_sources(
        project_root=project,
        managed_config_dir=managed,
        managed_directory="skills",
        environ={"XDG_CONFIG_HOME": str(absolute_xdg)},
    )
    fallback = skill_sources(
        project_root=project,
        managed_config_dir=managed,
        managed_directory="skills",
        environ={"XDG_CONFIG_HOME": "relative/config"},
    )

    assert [source.name for source in sources] == [
        "project",
        "managed",
        "global",
    ]
    assert sources[0].path == (project / ".agents/skills").resolve()
    assert sources[1].path == (managed / "skills").resolve()
    assert sources[2].path == (absolute_xdg / "agents/skills").resolve()
    assert fallback[2].path == (Path.home() / ".config/agents/skills").resolve()


def test_registry_prioritizes_project_then_managed_then_global(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    managed = tmp_path / "managed"
    xdg = tmp_path / "xdg"
    project.mkdir()
    managed.mkdir()
    _install_skill(project, ".agents/skills", "duplicate", "project copy")
    _install_skill(managed, "skills", "duplicate", "managed copy")
    _install_skill(managed, "skills", "managed-only", "managed only")
    _install_skill(xdg, "agents/skills", "duplicate", "global copy")
    _install_skill(xdg, "agents/skills", "global-only", "global only")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    registry = build_agent_registry(
        managed,
        _NoopClientManager(),
        project_root=project,
        dynamic_mcp_tools=False,
        dynamic_skill_tools=False,
    )

    assert list(registry.skills) == ["duplicate", "managed-only", "global-only"]
    assert registry.skills["duplicate"].source == "project"
    assert registry.skills["managed-only"].source == "managed"
    assert registry.skills["global-only"].source == "global"
    assert (
        sum(
            "duplicate Skill 'duplicate'" in warning
            for warning in registry.skill_warnings
        )
        == 2
    )


def test_invalid_project_duplicate_falls_back_to_managed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    managed = tmp_path / "managed"
    xdg = tmp_path / "xdg"
    (project / ".agents/skills/fallback").mkdir(parents=True)
    managed.mkdir()
    _install_skill(managed, "skills", "fallback", "managed valid")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    registry = build_agent_registry(
        managed,
        _NoopClientManager(),
        project_root=project,
        dynamic_mcp_tools=False,
        dynamic_skill_tools=False,
    )

    assert registry.skills["fallback"].source == "managed"
    assert any(
        "project:" in warning and "missing SKILL.md" in warning
        for warning in registry.skill_warnings
    )


def test_multi_source_scan_shares_entry_and_skill_budgets(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    managed = tmp_path / "managed"
    project.mkdir()
    managed.mkdir()
    _install_skill(project, ".agents/skills", "project-skill", "project")
    _install_skill(managed, "skills", "managed-skill", "managed")
    sources = (
        SkillSource("project", project, ".agents/skills"),
        SkillSource("managed", managed, "skills"),
    )

    by_count = scan_skill_sources(
        sources,
        max_skills=1,
        max_related_files=100,
        max_scan_entries=100,
        max_path_bytes=10_000,
        max_entry_bytes=10_000,
    )

    by_scan = scan_skill_sources(
        sources,
        max_skills=10,
        max_related_files=100,
        max_scan_entries=3,
        max_path_bytes=10_000,
        max_entry_bytes=10_000,
    )
    by_path = scan_skill_sources(
        sources,
        max_skills=10,
        max_related_files=100,
        max_scan_entries=100,
        max_path_bytes=len(b"guide.md"),
        max_entry_bytes=10_000,
    )

    assert list(by_count.skills) == ["project-skill"]
    assert list(by_scan.skills) == ["project-skill"]
    assert any("scan stopped" in warning for warning in by_scan.warnings)
    assert by_path.skills["project-skill"].related_files == ["guide.md"]
    assert by_path.skills["managed-skill"].related_files == []
    assert by_path.path_bytes == len(b"guide.md")
    assert any(
        "path budget is exhausted" in warning for warning in by_path.warnings
    )


@pytest.mark.asyncio
async def test_local_session_adds_its_workdir_project_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    default_project = workspace / "default"
    session_project = workspace / "session"
    managed = tmp_path / "managed"
    xdg = tmp_path / "xdg"
    default_project.mkdir(parents=True)
    session_project.mkdir(parents=True)
    managed.mkdir()
    _install_skill(
        default_project, ".agents/skills", "default-skill", "default"
    )
    _install_skill(
        session_project, ".agents/skills", "session-skill", "session"
    )
    _configure(
        monkeypatch,
        workspace=workspace,
        state_dir=tmp_path / "state",
        config_dir=managed,
        xdg_config_home=xdg,
    )
    session = get_tool_session_store().create_session(workdir=session_project)

    default = await agent_ops.list_agent_skills_dispatch_execute()
    scoped = await agent_ops.list_agent_skills_dispatch_execute(
        session.session_id
    )
    activated = await agent_ops.activate_agent_skill_dispatch_execute(
        "session-skill", session.session_id
    )

    assert [row["name"] for row in default.skills] == []
    assert [row["name"] for row in scoped.skills] == ["session-skill"]
    assert scoped.skills[0]["source"] == "project"
    assert activated.source == "project"
    assert "session" in activated.content


@pytest.mark.asyncio
async def test_remote_session_dispatches_skill_operations_to_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    managed = tmp_path / "managed"
    managed.mkdir()
    _configure(
        monkeypatch,
        workspace=workspace,
        state_dir=tmp_path / "state",
        config_dir=managed,
        xdg_config_home=tmp_path / "xdg",
    )
    session = get_tool_session_store().create_session(
        target="remote",
        workdir="/srv/project",
        machine="edge",
        worker_session_id="worker123",
    )
    calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_call(remote_session, tool: str, args: dict[str, Any]):
        assert remote_session.session_id == session.session_id
        calls.append((tool, args))
        source_path = "/srv/project/.agents/skills"
        if tool == "list_agent_skills":
            return {
                "sources": [{"source": "project", "path": source_path}],
                "skills": [
                    {
                        "name": "remote-skill",
                        "source": "project",
                        "source_path": source_path,
                        "entry_path": ".agents/skills/remote-skill/SKILL.md",
                        "description": "Remote.",
                        "related_files": ["guide.md"],
                    }
                ],
                "warnings": [],
            }
        if tool == "activate_agent_skill":
            return {
                "name": "remote-skill",
                "source": "project",
                "source_path": source_path,
                "entry_path": ".agents/skills/remote-skill/SKILL.md",
                "description": "Remote.",
                "content": "# Remote\n",
                "bytes": 9,
                "related_files": ["guide.md"],
            }
        return {
            "name": "remote-skill",
            "source": "project",
            "source_path": source_path,
            "path": "guide.md",
            "content": "guide",
            "bytes": 5,
        }

    monkeypatch.setattr(agent_ops, "call_remote_session_tool", fake_call)

    listed = await agent_ops.list_agent_skills_dispatch_execute(
        session.session_id
    )
    activated = await agent_ops.activate_agent_skill_dispatch_execute(
        "remote-skill", session.session_id
    )
    related = await agent_ops.read_agent_skill_file_dispatch_execute(
        "remote-skill", "guide.md", session.session_id
    )

    assert listed.skills[0]["source"] == "project"
    assert activated.content == "# Remote\n"
    assert related.content == "guide"
    assert calls == [
        ("list_agent_skills", {}),
        ("activate_agent_skill", {"name": "remote-skill"}),
        ("read_agent_skill_file", {"name": "remote-skill", "path": "guide.md"}),
    ]


@pytest.mark.asyncio
async def test_worker_executes_session_scoped_skill_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    project.mkdir(parents=True)
    managed = tmp_path / "managed"
    managed.mkdir()
    _install_skill(project, ".agents/skills", "worker-skill", "worker")
    _configure(
        monkeypatch,
        workspace=workspace,
        state_dir=tmp_path / "state",
        config_dir=managed,
        xdg_config_home=tmp_path / "xdg",
    )
    session = get_tool_session_store().create_session(workdir=project)

    listed = await execute_worker_tool(
        "list_agent_skills", {"session_id": session.session_id}
    )
    activated = await execute_worker_tool(
        "activate_agent_skill",
        {"session_id": session.session_id, "name": "worker-skill"},
    )

    assert listed.skills[0]["name"] == "worker-skill"
    assert listed.skills[0]["source"] == "project"
    assert activated.source == "project"


def test_registry_fingerprint_tracks_project_and_global_sources(
    tmp_path: Path,
) -> None:
    managed = tmp_path / "managed"
    project = tmp_path / "project"
    xdg = tmp_path / "xdg"
    managed.mkdir()
    project.mkdir()
    sources = (
        SkillSource("project", project, ".agents/skills"),
        SkillSource("managed", managed, "skills"),
        SkillSource("global", xdg, "agents/skills"),
    )
    before = agent_registry_fingerprint(managed, sources)
    _install_skill(project, ".agents/skills", "project-skill", "project")
    after_project = agent_registry_fingerprint(managed, sources)
    _install_skill(xdg, "agents/skills", "global-skill", "global")
    after_global = agent_registry_fingerprint(managed, sources)

    assert before != after_project
    assert after_project != after_global
