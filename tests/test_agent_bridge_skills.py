from local_shell_mcp.agent_bridge import (
    SkillRecord,
    activate_skill,
    make_unique_tool_name,
    scan_agent_skills,
)


def test_scan_agent_skills_reads_skill_md(tmp_path):
    skill_dir = tmp_path / "skills" / "paper-writer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "# Paper Writer\n\nHelps draft ML papers.\n",
        encoding="utf-8",
    )
    (skill_dir / "template.md").write_text("template", encoding="utf-8")

    result = scan_agent_skills(tmp_path, "skills")

    assert result.warnings == []
    assert result.skills == {
        "paper-writer": SkillRecord(
            name="paper-writer",
            entry_path="skills/paper-writer/SKILL.md",
            description="Helps draft ML papers.",
            related_files=[
                "skills/paper-writer/SKILL.md",
                "skills/paper-writer/template.md",
            ],
        )
    }


def test_scan_agent_skills_skips_missing_entry(tmp_path):
    (tmp_path / "skills" / "broken").mkdir(parents=True)

    result = scan_agent_skills(tmp_path, "skills")

    assert result.skills == {}
    assert result.warnings == ["Skipping skill broken: missing SKILL.md"]


def test_activate_skill_returns_content_and_related_files(tmp_path):
    skill_dir = tmp_path / "skills" / "debugging"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "# Debugging\n\nFind root causes.\n", encoding="utf-8"
    )

    records = scan_agent_skills(tmp_path, "skills").skills
    payload = activate_skill(tmp_path, records["debugging"])

    assert payload["name"] == "debugging"
    assert payload["entry_path"] == "skills/debugging/SKILL.md"
    assert payload["content"] == "# Debugging\n\nFind root causes.\n"
    assert payload["related_files"] == ["skills/debugging/SKILL.md"]


def test_make_unique_tool_name_sanitizes_and_hashes_collisions():
    seen: set[str] = set()
    first = make_unique_tool_name("activate_skill", "paper-writer", seen)
    second = make_unique_tool_name("activate_skill", "paper writer", seen)

    assert first == "activate_skill__paper_writer"
    assert second.startswith("activate_skill__paper_writer__")
    assert first != second
