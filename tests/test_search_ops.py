import shutil

import pytest

from local_shell_mcp.config.settings import clear_settings_cache, get_settings
from local_shell_mcp.ops.search import (
    glob_search_execute,
    grep_search_execute,
    search_execute,
    tree_view_execute,
)
from local_shell_mcp.tool_session.store import get_tool_session_store


def _create_session() -> str:
    store = get_tool_session_store()
    store.clear()
    return store.create_session(workdir=".").session_id


@pytest.mark.asyncio
async def test_tree_reports_existing_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "project" / "src").mkdir(parents=True)
    (tmp_path / "project" / "README.md").write_text("hello", encoding="utf-8")

    session_id = _create_session()

    result = await tree_view_execute(session_id, "project")

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

    session_id = _create_session()

    result = await tree_view_execute(session_id, ".", max_entries=100)

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

    session_id = _create_session()

    result = await tree_view_execute(session_id, "missing/project")

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


@pytest.mark.asyncio
async def test_glob_finds_matching_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('x')", encoding="utf-8")
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")

    session_id = _create_session()

    result = await glob_search_execute(session_id, "*.py", cwd=".")

    assert result.paths == ["src/app.py"]


@pytest.mark.asyncio
async def test_tree_and_glob_resolve_relative_to_session_workdir(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    (tmp_path / "outer.txt").write_text("outer", encoding="utf-8")
    (tmp_path / "project" / "src").mkdir(parents=True)
    (tmp_path / "project" / "src" / "app.py").write_text(
        "print('x')", encoding="utf-8"
    )

    store = get_tool_session_store()
    store.clear()
    session_id = store.create_session(workdir="project").session_id

    tree = await tree_view_execute(session_id, ".", depth=2)
    glob = await glob_search_execute(session_id, "*.py", cwd=".")

    assert tree.root == str(tmp_path / "project")
    assert "src/" in tree.entries
    assert "outer.txt" not in tree.entries
    assert glob.paths == ["project/src/app.py"]


@pytest.mark.asyncio
async def test_grep_search_returns_grounded_numbered_matches(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    if not shutil.which(get_settings().rg_bin):
        pytest.skip("missing rg")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "alpha\nneedle here\ngamma\n", encoding="utf-8"
    )

    session_id = _create_session()

    result = await grep_search_execute(
        "needle", cwd=".", regex=False, session_id=session_id
    )

    assert result.ok is True
    assert result.count == 1
    match = result.matches[0]
    assert match.path == "src/app.py"
    assert match.numbered_line is not None
    assert match.numbered_line.startswith("[src/app.py#")
    assert match.numbered_line.endswith("]\n2:needle here")
    assert match.snapshot_id
    assert match.file_sha256
    assert match.seen_range is not None
    assert match.seen_range.model_dump() == {"start": 2, "end": 2}
    assert result.numbered_content.startswith("src/app.py\n[src/app.py#")
    assert result.numbered_content.endswith("]\n2:needle here")


@pytest.mark.asyncio
async def test_high_level_search_scopes_to_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    clear_settings_cache()
    if not shutil.which(get_settings().rg_bin):
        pytest.skip("missing rg")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "app.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "tests" / "test_app.py").write_text(
        "needle\n", encoding="utf-8"
    )

    session_id = _create_session()

    result = await search_execute(
        "needle", paths="src", regex=False, session_id=session_id
    )

    assert result.ok is True
    assert result.count == 1
    assert result.matches[0].numbered_line is not None
    assert result.matches[0].numbered_line.startswith("[src/app.py#")
    assert result.matches[0].numbered_line.endswith("]\n1:needle")
    assert result.matches[0].path == "src/app.py"


@pytest.mark.asyncio
async def test_mcp_search_facade_returns_grounded_results(
    tmp_path, monkeypatch
):
    from local_shell_mcp.server.mcp.app import build_mcp
    from tests.helpers import mcp_structured

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()
    if not shutil.which(get_settings().rg_bin):
        pytest.skip("missing rg")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("needle\n", encoding="utf-8")

    session = mcp_structured(
        await build_mcp().call_tool("session_start", {"workdir": "."})
    )
    payload = mcp_structured(
        await build_mcp().call_tool(
            "search",
            {
                "session_id": session["session_id"],
                "pattern": "needle",
                "paths": "src",
                "regex": False,
            },
        )
    )

    assert payload["matches"][0]["path"] == "src/app.py"
    assert payload["matches"][0]["snapshot_id"]
    assert payload["numbered_content"].startswith("src/app.py\n[src/app.py#")
    assert payload["numbered_content"].endswith("]\n1:needle")
