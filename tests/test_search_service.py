import shutil

import pytest

from local_shell_mcp import persistence
from local_shell_mcp.config import settings as settings_module
from local_shell_mcp.config.settings import clear_settings_cache, get_settings
from local_shell_mcp.ops.search import service as search_service_module
from local_shell_mcp.ops.search.composition import (
    build_local_search_runner,
    build_search_service,
)
from local_shell_mcp.ops.search.service import RemoteSearchClient, SearchRequest
from local_shell_mcp.schemas.result_models.search import (
    GrepMatch,
    GrepSearchOutput,
)
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


def test_search_path_access_and_scope_parsing_are_explicit(
    tmp_path, monkeypatch
):
    store, settings = _store_and_settings(tmp_path, monkeypatch)
    workdir = tmp_path / "work"
    workdir.mkdir()
    target = workdir / "demo.txt"
    target.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    (workdir / "nested").mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    runner = build_local_search_runner(settings, store)

    assert (
        runner.paths.resolve_in_workdir(
            str(workdir), "demo.txt", must_exist=True
        )
        == target
    )
    with pytest.raises(ValueError, match="Path escapes session workdir"):
        runner.paths.resolve_in_workdir(
            str(workdir), "../outside.txt", must_exist=True
        )

    path_args, glob_args, line_scopes = runner._split_scopes(
        workdir,
        ["*.py", "demo.txt:1-2", "demo.txt:3-4"],
    )
    assert path_args == ["demo.txt"]
    assert glob_args == ["*.py"]
    assert line_scopes == {str(target): ((1, 4),)}

    _path_args, _glob_args, unrestricted = runner._split_scopes(
        workdir,
        ["demo.txt:1-1", "demo.txt"],
    )
    assert unrestricted == {}
    with pytest.raises(
        ValueError, match="line selectors are supported only for files"
    ):
        runner._split_scopes(workdir, ["nested:1-2"])


def test_search_grounding_failures_leave_matches_usable(tmp_path, monkeypatch):
    store, settings = _store_and_settings(tmp_path, monkeypatch)
    runner = build_local_search_runner(settings, store)
    missing_line = GrepMatch(
        path="demo.txt", line=None, column=1, text="needle"
    )
    assert runner._ground_match(missing_line, tmp_path, None) == missing_line

    def fail_read(*_args, **_kwargs):
        raise ValueError("file changed")

    monkeypatch.setattr(
        search_service_module.SearchGrounding, "read", fail_read
    )
    match = GrepMatch(path="demo.txt", line=1, column=1, text="needle")
    assert runner._ground_match(match, tmp_path, None) == match
    displayed, numbered = runner._display_output(
        [search_service_module._RawSearchMatch(match, None)],
        tmp_path,
        None,
        1,
    )
    assert displayed == []
    assert numbered == ""


@pytest.mark.asyncio
async def test_local_search_runner_reports_process_start_failure(
    tmp_path, monkeypatch
):
    store, settings = _store_and_settings(tmp_path, monkeypatch)
    runner = build_local_search_runner(settings, store)

    async def fail_spawn(*_args, **_kwargs):
        raise OSError("not installed")

    monkeypatch.setattr(
        search_service_module.asyncio, "create_subprocess_exec", fail_spawn
    )
    result = await runner.search(
        SearchRequest(pattern="needle", regex=False, skip=-5),
        workdir=str(tmp_path),
    )

    assert result.ok is False
    assert result.count == 0
    assert result.skipped == 0
    assert "not installed" in result.stderr


@pytest.mark.asyncio
async def test_search_service_routes_remote_binding_or_rejects_worker_runtime(
    tmp_path, monkeypatch
):
    store, settings = _store_and_settings(tmp_path, monkeypatch)
    session = store.create_session(
        target="remote",
        workdir="/remote/work",
        machine="worker-a",
        worker_session_id="WORKER01",
    )
    worker_service = build_search_service(settings, store, remote=None)
    with pytest.raises(ValueError, match="remote Search is unavailable"):
        await worker_service.search(session.session_id, "needle")

    calls = []
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

    async def fake_call(binding, tool, args):
        calls.append((binding, tool, args))
        return output.model_dump(mode="json")

    controller_service = build_search_service(
        settings,
        store,
        remote=RemoteSearchClient(call=fake_call),
    )
    result = await controller_service.search(
        session.session_id,
        "needle",
        paths="src",
        regex=False,
        max_results=3,
        skip=1,
        gitignore=False,
    )

    assert result == output
    assert len(calls) == 1
    binding, tool, args = calls[0]
    assert isinstance(binding, RemoteSessionBinding)
    assert binding.session_id == session.session_id
    assert tool == "search"
    assert args["paths"] == "src"
    assert args["max_results"] == 3
