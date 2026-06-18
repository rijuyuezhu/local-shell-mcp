import shutil

import pytest

from local_shell_mcp.config.settings import clear_settings_cache, get_settings
from local_shell_mcp.ops.search import (
    glob_search_execute,
    grep_search_execute,
    tree_view_execute,
)


@pytest.mark.asyncio
async def test_tree_reports_existing_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "project" / "src").mkdir(parents=True)
    (tmp_path / "project" / "README.md").write_text("hello", encoding="utf-8")

    result = await tree_view_execute("project")

    assert result.exists is True
    assert result.is_directory is True
    assert "src/" in result.entries
    assert "README.md" in result.entries


@pytest.mark.asyncio
async def test_tree_clamps_entries_without_sorting_entire_tree(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_TREE_ENTRIES", "3")
    clear_settings_cache()
    for idx in range(10):
        (tmp_path / f"file-{idx}.txt").write_text("x", encoding="utf-8")

    result = await tree_view_execute(".", max_entries=100)

    assert result.count == 3
    assert len(result.entries) == 3
    assert result.truncated is True


@pytest.mark.asyncio
async def test_tree_returns_context_for_missing_directory(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "actual").mkdir()

    result = await tree_view_execute("missing/project")

    assert result.exists is False
    assert result.is_directory is False
    assert result.nearest_existing_parent == str(tmp_path)
    assert result.nearest_parent_entries is not None
    assert "actual/" in result.nearest_parent_entries
    assert result.message is not None
    assert "Path does not exist" in result.message


@pytest.mark.asyncio
async def test_grep_accepts_query_starting_with_dash(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    if not shutil.which(get_settings().rg_bin):
        pytest.skip("missing rg")
    term = chr(45) + "needle"
    (tmp_path / "dash.txt").write_text(term + "\n", encoding="utf-8")

    result = await grep_search_execute(term, cwd=".", regex=False)

    assert result.ok is True
    assert result.count == 1
    assert result.matches[0].path is not None
    assert result.matches[0].path.endswith("dash.txt")


def test_glob_finds_matching_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('x')", encoding="utf-8")
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")

    result = glob_search_execute("*.py", cwd=".")

    assert result.paths == ["src/app.py"]
