import inspect
import shutil

import pytest

from local_shell_mcp.config.settings import Settings, clear_settings_cache
from local_shell_mcp.executors.runtime_services import (
    configure_runtime_services,
)
from local_shell_mcp.executors.search_composition import (
    build_controller_tool_catalog,
)
from local_shell_mcp.persistence import configure_state_store
from local_shell_mcp.remote_worker.search_composition import (
    build_worker_dispatcher_with_search,
)
from local_shell_mcp.schemas.result_models.search import (
    GlobSearchOutput,
    TreeViewOutput,
)
from local_shell_mcp.tool_session import configure_tool_session_store
from local_shell_mcp.tools.registry import search as search_registry_module
from local_shell_mcp.tools.registry.search import SearchToolRegistry


@pytest.fixture(autouse=True)
def _restore_global_runtime_services():
    yield
    configure_tool_session_store(None)
    configure_state_store(None)
    clear_settings_cache()


def _settings(tmp_path, monkeypatch) -> Settings:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    return Settings()


@pytest.mark.asyncio
async def test_controller_catalog_binds_search_without_changing_tool_signature(
    tmp_path, monkeypatch
):
    if not shutil.which("rg"):
        pytest.skip("missing rg")
    settings = _settings(tmp_path, monkeypatch)
    services = configure_runtime_services(settings)
    (tmp_path / "demo.txt").write_text("needle\n", encoding="utf-8")
    session = services.tool_session_store.create_session(workdir=tmp_path)

    catalog = build_controller_tool_catalog(
        settings, services.tool_session_store
    )
    registry = next(
        registry
        for registry in catalog.registries
        if isinstance(registry, SearchToolRegistry)
    )
    bound_search = next(
        tool for tool in registry._enabled_tools() if tool.name == "search"
    )

    assert inspect.signature(bound_search.func) == inspect.signature(
        search_registry_module.search.func
    )
    result = await bound_search.func(
        session.session_id,
        "needle",
        regex=False,
        gitignore=False,
    )
    assert result.ok is True
    assert result.count == 1
    assert result.matches[0].snapshot_id is not None


@pytest.mark.asyncio
async def test_worker_dispatcher_uses_composed_search_override(
    tmp_path, monkeypatch
):
    if not shutil.which("rg"):
        pytest.skip("missing rg")
    settings = _settings(tmp_path, monkeypatch)
    services = configure_runtime_services(settings)
    dispatcher = build_worker_dispatcher_with_search(
        settings, services.tool_session_store
    )
    (tmp_path / "demo.txt").write_text("needle\n", encoding="utf-8")
    session = await dispatcher.execute(
        "session_start",
        {
            "workdir": str(tmp_path),
            "target": "local",
            "machine": None,
            "label": None,
        },
    )

    import local_shell_mcp.ops.search as search_ops

    async def legacy_search_should_not_run(*_args, **_kwargs):
        raise AssertionError("worker Search fell back to legacy search_execute")

    monkeypatch.setattr(
        search_ops, "search_execute", legacy_search_should_not_run
    )
    result = await dispatcher.execute(
        "search",
        {
            "session_id": session.session_id,
            "pattern": "needle",
            "paths": None,
            "regex": False,
            "case_sensitive": True,
            "max_results": None,
            "skip": 0,
            "gitignore": False,
        },
    )

    assert result.ok is True
    assert result.count == 1
    assert result.matches[0].session_id == session.session_id


@pytest.mark.asyncio
async def test_search_registry_unbound_service_and_legacy_wrappers(monkeypatch):
    registry = SearchToolRegistry()
    with pytest.raises(RuntimeError, match="Search service is not bound"):
        await registry._bound_search("SESSION01", "needle")

    tree_output = TreeViewOutput(
        root=".",
        exists=True,
        is_directory=True,
        entries=[],
        count=0,
        truncated=False,
    )
    glob_output = GlobSearchOutput(paths=["src/app.py"])
    calls = []

    async def fake_tree(session_id, cwd, depth, max_entries):
        calls.append(("tree", session_id, cwd, depth, max_entries))
        return tree_output

    async def fake_glob(session_id, pattern, cwd, max_results):
        calls.append(("glob", session_id, pattern, cwd, max_results))
        return glob_output

    monkeypatch.setattr(search_registry_module, "tree_view_execute", fake_tree)
    monkeypatch.setattr(
        search_registry_module, "glob_search_execute", fake_glob
    )

    assert (
        await search_registry_module.tree_view.func("SESSION01", "src", 2, 10)
        == tree_output
    )
    assert (
        await search_registry_module.glob_search.func(
            "SESSION01", "*.py", "src", 20
        )
        == glob_output
    )
    assert calls == [
        ("tree", "SESSION01", "src", 2, 10),
        ("glob", "SESSION01", "*.py", "src", 20),
    ]
