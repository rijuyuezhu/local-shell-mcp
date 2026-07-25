from __future__ import annotations

import os
from pathlib import Path

import pytest

import local_shell_mcp.agent_bridge.skills as skills
from local_shell_mcp.agent_bridge.models import SkillRecord
from local_shell_mcp.agent_bridge.registry import make_unique_tool_name


def _install_skill(
    config_dir: Path,
    name: str = "debugging",
    *,
    content: str = "# Debugging\n\nFind root causes.\n",
) -> Path:
    skill_dir = config_dir / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


def test_scan_agent_skills_reads_skill_md_with_bounded_related_paths(tmp_path):
    skill_dir = _install_skill(
        tmp_path,
        "paper-writer",
        content="# Paper Writer\n\nHelps draft ML papers.\n",
    )
    (skill_dir / "template.md").write_text("template", encoding="utf-8")

    result = skills.scan_agent_skills(tmp_path, "skills")

    assert result.warnings == []
    assert result.scanned_entries >= 3
    assert result.skills == {
        "paper-writer": SkillRecord(
            name="paper-writer",
            source="managed",
            source_path=str((tmp_path / "skills").resolve()),
            entry_path="skills/paper-writer/SKILL.md",
            description="Helps draft ML papers.",
            related_files=["template.md"],
        )
    }


def test_scan_agent_skills_skips_missing_entry(tmp_path):
    (tmp_path / "skills" / "broken").mkdir(parents=True)

    result = skills.scan_agent_skills(tmp_path, "skills")

    assert result.skills == {}
    assert len(result.warnings) == 1
    assert "missing SKILL.md" in result.warnings[0]


def test_scan_agent_skills_skips_symlinked_entry(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    skill_dir = tmp_path / "skills" / "escape"
    skill_dir.mkdir(parents=True)
    try:
        (skill_dir / "SKILL.md").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    result = skills.scan_agent_skills(tmp_path, "skills")

    assert result.skills == {}
    assert any(
        "regular file" in warning or "symlink" in warning
        for warning in result.warnings
    )


def test_scan_agent_skills_rejects_directories_outside_config_root(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    outside = tmp_path / "outside"

    relative_result = skills.scan_agent_skills(config_dir, "../outside")
    absolute_result = skills.scan_agent_skills(config_dir, str(outside))

    assert relative_result.skills == {}
    assert absolute_result.skills == {}
    assert "inside config directory" in relative_result.warnings[0]
    assert "inside config directory" in absolute_result.warnings[0]


def test_activate_and_read_related_skill_file(tmp_path):
    skill_dir = _install_skill(tmp_path)
    (skill_dir / "guide.md").write_bytes(b"Reproduce first.\r\n")
    record = skills.scan_agent_skills(tmp_path, "skills").skills["debugging"]

    activated = skills.activate_skill(tmp_path, record)
    related = skills.read_agent_skill_file(
        tmp_path, "debugging", "guide.md", "skills"
    )

    assert activated["name"] == "debugging"
    assert activated["source"] == "managed"
    assert activated["source_path"] == str((tmp_path / "skills").resolve())
    assert activated["entry_path"] == "skills/debugging/SKILL.md"
    assert activated["content"] == "# Debugging\n\nFind root causes.\n"
    assert activated["bytes"] == (skill_dir / "SKILL.md").stat().st_size
    assert activated["related_files"] == ["guide.md"]
    assert related == {
        "name": "debugging",
        "source": "managed",
        "source_path": str((tmp_path / "skills").resolve()),
        "path": "guide.md",
        "content": "Reproduce first.\n",
        "bytes": len(b"Reproduce first.\r\n"),
    }


def test_code_humanizer_style_front_matter_and_large_body(tmp_path):
    description = (
        "Use when code was written by an AI coding agent and needs structural cleanup "
        "— or when asked to deslop, remove AI slop, or humanize code."
    )
    body = "\n".join(
        f"## Pattern {index}\nEvidence and remediation." for index in range(300)
    )
    content = (
        "---\n"
        "name: code-humanizer\n"
        "version: 0.1.0\n"
        f"description: {description}\n"
        "license: MIT\n"
        "compatibility: any-agent\n"
        "---\n\n"
        "# Code Humanizer\n\n"
        f"{body}\n"
    )
    _install_skill(tmp_path, "code-humanizer", content=content)

    result = skills.scan_agent_skills(tmp_path)
    record = result.skills["code-humanizer"]
    activated = skills.activate_skill(tmp_path, record)

    assert result.warnings == []
    assert record.description == description
    assert record.related_files == []
    assert activated["content"].startswith("---\nname: code-humanizer\n")
    assert activated["bytes"] > 10_000


def test_cloned_skill_ignores_vcs_and_cache_metadata(tmp_path):
    skill_dir = _install_skill(tmp_path, "cloned")
    (skill_dir / ".git" / "objects").mkdir(parents=True)
    (skill_dir / ".git" / "objects" / "pack.bin").write_bytes(b"\x00pack")
    (skill_dir / ".hg").mkdir()
    (skill_dir / ".hg" / "store").write_text("metadata", encoding="utf-8")
    (skill_dir / "__pycache__").mkdir()
    (skill_dir / "__pycache__" / "cache.pyc").write_bytes(b"\x00pyc")
    (skill_dir / "README.md").write_text(
        "# Installed skill\n", encoding="utf-8"
    )

    record = skills.scan_agent_skills(tmp_path).skills["cloned"]

    assert record.related_files == ["README.md"]
    assert not any(path.startswith(".git/") for path in record.related_files)
    assert not any(path.startswith(".hg/") for path in record.related_files)
    assert not any(
        path.startswith("__pycache__/") for path in record.related_files
    )


def test_read_related_file_rejects_entry_and_traversal(tmp_path):
    _install_skill(tmp_path)

    with pytest.raises(ValueError, match="activate_agent_skill"):
        skills.read_agent_skill_file(tmp_path, "debugging", "SKILL.md")
    with pytest.raises(ValueError, match="relative"):
        skills.read_agent_skill_file(tmp_path, "debugging", "../outside.md")
    with pytest.raises(ValueError, match="portable POSIX"):
        skills.read_agent_skill_file(tmp_path, "debugging", r"docs\guide.md")


def test_skill_name_and_file_path_validation():
    for value in (
        None,
        "",
        " name",
        "name ",
        ".",
        "..",
        "a/b",
        r"a\b",
        "x" * 256,
        "a\x01",
    ):
        with pytest.raises(ValueError):
            skills.validate_skill_name(value)  # type: ignore[arg-type]

    for value in (
        None,
        "",
        r"a\b",
        "a:b",
        "a\x01",
        "/a",
        "../a",
        ".",
        "a//b",
        "a/./b",
    ):
        with pytest.raises(ValueError):
            skills.validate_skill_file_path(value)  # type: ignore[arg-type]

    assert skills.validate_skill_name("合法-name") == "合法-name"
    assert skills.validate_skill_file_path("docs/guide.md") == Path(
        "docs/guide.md"
    )


def test_regular_file_reads_are_bounded_and_normalized(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    entry = root / "entry.md"
    entry.write_bytes(b"line\r\nnext\r")

    content, size, resolved = skills._open_regular_file(entry, root, 100)

    assert content == "line\nnext\n"
    assert size == len(b"line\r\nnext\r")
    assert resolved == entry.resolve()
    with pytest.raises(ValueError, match="maximum"):
        skills._open_regular_file(entry, root, 1)
    with pytest.raises(ValueError, match="readable regular"):
        skills._open_regular_file(root / "missing", root, 100)


def test_related_file_scan_honors_budgets(tmp_path):
    skill_dir = _install_skill(tmp_path)
    for name in ("a.txt", "b.txt"):
        (skill_dir / name).write_text(name, encoding="utf-8")

    result = skills.scan_agent_skills(
        tmp_path,
        max_related_files=1,
        max_scan_entries=100,
        max_path_bytes=100,
    )

    assert len(result.skills["debugging"].related_files) == 1
    assert any("truncated" in warning for warning in result.warnings)


def test_scan_agent_skills_reports_scandir_failure(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    original_scandir = os.scandir

    def fail_scandir(path):
        if Path(path) == skills_dir.resolve():
            raise OSError("racing directory")
        return original_scandir(path)

    monkeypatch.setattr(skills.os, "scandir", fail_scandir)

    result = skills.scan_agent_skills(tmp_path)

    assert result.skills == {}
    assert result.warnings == [
        "Could not scan skills directory skills: racing directory"
    ]


def test_make_unique_tool_name_sanitizes_and_hashes_collisions():
    seen: set[str] = set()
    first = make_unique_tool_name("activate_skill", "paper-writer", seen)
    second = make_unique_tool_name("activate_skill", "paper writer", seen)

    assert first == "activate_skill__paper_writer"
    assert second.startswith("activate_skill__paper_writer__")
    assert first != second


def test_make_unique_tool_name_preserves_empty_raw_name_segment():
    assert make_unique_tool_name("activate_skill", "!!!", set()) == (
        "activate_skill__unnamed"
    )
