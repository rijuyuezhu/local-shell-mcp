import shutil

import pytest

from local_shell_mcp import persistence
from local_shell_mcp.config import settings as settings_module
from local_shell_mcp.config.settings import clear_settings_cache, get_settings
from local_shell_mcp.ops.search_composition import build_search_service
from local_shell_mcp.ops.search_service import RemoteSearchClient, SearchRequest
from local_shell_mcp.schemas.result_models.search import GrepSearchOutput
from local_shell_mcp.tool_session import store as store_module
from local_shell_mcp.tool_session.bindings import RemoteSessionBinding


def _store_and_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    settings = get_settings()
    store = store_module.ToolSessionStore(
        state_store=persistence.FileStateStore(lambda: settings.state_dir),
        settings_provider=lambda: settings,
    )
    store.clear()
    return store, settings


def _boom(*_args, **_kwargs):
    raise AssertionError(
        "migrated Search path reacquired an ambient dependency"
    )


@pytest.mark.asyncio
async def test_search_service_does_not_reacquire_ambient_dependencies(
    tmp_path, monkeypatch
):
    if not shutil.which("rg"):
        pytest.skip("missing rg")
    store, settings = _store_and_settings(tmp_path, monkeypatch)
    (tmp_path / "demo.txt").write_text("needle\n", encoding="utf-8")
    session = store.create_session(workdir=tmp_path)
    service = build_search_service(settings, store, remote=None)

    monkeypatch.setattr(settings_module, "get_settings", _boom)
    monkeypatch.setattr(store_module, "get_tool_session_store", _boom)
    monkeypatch.setattr(persistence, "get_state_store", _boom)

    result = await service.search(
        session.session_id,
        "needle",
        regex=False,
        gitignore=False,
    )

    assert result.ok is True
    assert result.count == 1
    assert result.matches[0].session_id == session.session_id
    assert result.matches[0].snapshot_id is not None
    assert result.numbered_content


@pytest.mark.asyncio
async def test_search_service_resolves_fresh_workdir_per_operation(
    tmp_path, monkeypatch
):
    if not shutil.which("rg"):
        pytest.skip("missing rg")
    store, settings = _store_and_settings(tmp_path, monkeypatch)
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "one.txt").write_text("needle first\n", encoding="utf-8")
    (second / "two.txt").write_text("needle second\n", encoding="utf-8")
    session = store.create_session(workdir=first)
    service = build_search_service(settings, store, remote=None)

    first_result = await service.search(
        session.session_id,
        "needle",
        regex=False,
        gitignore=False,
    )
    store.change_session_workdir(session.session_id, second)
    second_result = await service.search(
        session.session_id,
        "needle",
        regex=False,
        gitignore=False,
    )

    assert [match.path for match in first_result.matches] == ["first/one.txt"]
    assert [match.path for match in second_result.matches] == ["second/two.txt"]


@pytest.mark.asyncio
async def test_remote_search_client_keeps_mapping_at_wire_boundary():
    calls = []
    binding = RemoteSessionBinding(
        session_id="SESSION01",
        workdir="/remote/work",
        machine="worker-a",
        worker_session_id="WORKER01",
    )
    output = GrepSearchOutput(
        ok=True,
        matches=[],
        displayed_lines=[],
        count=0,
        displayed_count=0,
        context_radius=0,
        skipped=0,
        truncated=False,
        stderr="",
        numbered_content="",
    )

    async def fake_call(remote_binding, tool, args):
        calls.append((remote_binding, tool, args))
        return output.model_dump(mode="json")

    client = RemoteSearchClient(call=fake_call)
    result = await client.search(
        binding,
        SearchRequest(
            pattern="needle",
            paths=["src", "tests/*.py"],
            regex=False,
            skip=2,
            gitignore=False,
        ),
    )

    assert result == output
    assert calls == [
        (
            binding,
            "search",
            {
                "pattern": "needle",
                "paths": ["src", "tests/*.py"],
                "regex": False,
                "case_sensitive": True,
                "max_results": None,
                "skip": 2,
                "gitignore": False,
            },
        )
    ]
