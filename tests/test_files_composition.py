import inspect

import pytest

from local_shell_mcp.config.settings import Settings, clear_settings_cache
from local_shell_mcp.executors.runtime_services import (
    configure_runtime_services,
)
from local_shell_mcp.executors.search_composition import (
    build_controller_tool_catalog,
)
from local_shell_mcp.persistence import configure_state_store
from local_shell_mcp.remote.manager import (
    RemoteManager,
    configure_remote_manager,
)
from local_shell_mcp.remote_worker.search_composition import (
    build_worker_dispatcher_with_search,
)
from local_shell_mcp.tool_session import configure_tool_session_store
from local_shell_mcp.tools.registry import files as files_registry_module
from local_shell_mcp.tools.registry import read as read_registry_module
from local_shell_mcp.tools.registry.files import FileToolRegistry
from local_shell_mcp.tools.registry.read import ReadToolRegistry


@pytest.fixture(autouse=True)
def _restore_global_runtime_services():
    configure_remote_manager(None)
    yield
    configure_remote_manager(None)
    configure_tool_session_store(None)
    configure_state_store(None)
    clear_settings_cache()


def _settings(tmp_path, monkeypatch) -> Settings:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    return Settings()


def _registry(catalog, registry_type):
    return next(
        registry
        for registry in catalog.registries
        if isinstance(registry, registry_type)
    )


def _tool(registry, name):
    return next(tool for tool in registry._enabled_tools() if tool.name == name)


@pytest.mark.asyncio
async def test_controller_files_and_read_use_explicit_service_without_ambient_fallback(
    tmp_path, monkeypatch
):
    settings = _settings(tmp_path, monkeypatch)
    services = configure_runtime_services(settings)
    (tmp_path / "demo.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    session = services.tool_session_store.create_session(workdir=tmp_path)
    catalog = build_controller_tool_catalog(
        settings,
        services.tool_session_store,
        RemoteManager(lambda: settings, state_store=services.state_store),
    )

    file_registry = _registry(catalog, FileToolRegistry)
    read_registry = _registry(catalog, ReadToolRegistry)

    assert inspect.signature(_tool(file_registry, "list_files").func) == (
        inspect.signature(files_registry_module.list_files.func)
    )
    assert inspect.signature(_tool(file_registry, "write_file").func) == (
        inspect.signature(files_registry_module.write_file.func)
    )
    assert inspect.signature(_tool(file_registry, "edit_lines").func) == (
        inspect.signature(files_registry_module.edit_lines.func)
    )
    assert inspect.signature(_tool(file_registry, "hashline_edit").func) == (
        inspect.signature(files_registry_module.hashline_edit.func)
    )
    assert inspect.signature(
        _tool(file_registry, "delete_file_or_dir").func
    ) == (inspect.signature(files_registry_module.delete_file_or_dir.func))
    assert inspect.signature(
        _tool(read_registry, "read").func
    ) == inspect.signature(read_registry_module.read.func)
    assert all(
        tool.session_admission == "handler"
        for tool in file_registry._enabled_tools()
    )
    assert _tool(read_registry, "read").session_admission == "handler"

    import local_shell_mcp.ops.files as files_ops
    import local_shell_mcp.ops.read as read_ops

    def ambient_files_should_not_run():
        raise AssertionError(
            "controller Files fell back to ambient dependencies"
        )

    async def legacy_read_should_not_run(*_args, **_kwargs):
        raise AssertionError("controller Read fell back to legacy read_execute")

    monkeypatch.setattr(
        files_ops, "_compat_files_dependencies", ambient_files_should_not_run
    )
    monkeypatch.setattr(read_ops, "read_execute", legacy_read_should_not_run)

    listed = await _tool(file_registry, "list_files").func(
        session.session_id, ".", False, 10
    )
    read = await _tool(read_registry, "read").func(
        session.session_id, "demo.txt:2"
    )

    assert any(entry.path == "demo.txt" for entry in listed.entries)
    assert read.kind == "file"
    assert read.content.endswith("2:beta")
    assert read.file is not None
    assert read.file.snapshot_id is not None


@pytest.mark.asyncio
async def test_controller_files_remote_wire_uses_owned_manager(
    tmp_path, monkeypatch
):
    settings = _settings(tmp_path, monkeypatch)
    services = configure_runtime_services(settings)
    session = services.tool_session_store.create_session(
        target="remote",
        workdir="/remote/work",
        machine="worker-a",
        worker_session_id="WORKER01",
    )
    manager = RemoteManager(lambda: settings, state_store=services.state_store)
    calls = []

    async def fake_call(machine, tool, args, timeout_s=None):
        calls.append((machine, tool, args, timeout_s))
        return {
            "ok": True,
            "data": {
                "limit_count": 10,
                "count": 0,
                "is_truncated": False,
                "entries": [],
            },
        }

    monkeypatch.setattr(manager, "call", fake_call)
    catalog = build_controller_tool_catalog(
        settings, services.tool_session_store, manager
    )
    file_registry = _registry(catalog, FileToolRegistry)

    result = await _tool(file_registry, "list_files").func(
        session.session_id, "src", False, 10
    )

    assert result.count == 0
    assert calls == [
        (
            "worker-a",
            "list_files",
            {
                "path": "src",
                "recursive": False,
                "max_entries": 10,
                "session_id": "WORKER01",
            },
            None,
        )
    ]


@pytest.mark.asyncio
async def test_worker_dispatcher_uses_composed_files_and_read_overrides(
    tmp_path, monkeypatch
):
    settings = _settings(tmp_path, monkeypatch)
    services = configure_runtime_services(settings)
    dispatcher = build_worker_dispatcher_with_search(
        settings, services.tool_session_store
    )
    (tmp_path / "demo.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    session = await dispatcher.execute(
        "session_start",
        {
            "workdir": str(tmp_path),
            "target": "local",
            "machine": None,
            "label": None,
        },
    )

    import local_shell_mcp.ops.files as files_ops
    import local_shell_mcp.ops.read as read_ops

    async def legacy_files_should_not_run(*_args, **_kwargs):
        raise AssertionError("worker Files fell back to legacy dispatch")

    async def legacy_read_should_not_run(*_args, **_kwargs):
        raise AssertionError("worker Read fell back to legacy read_execute")

    monkeypatch.setattr(
        files_ops, "list_files_dispatch_execute", legacy_files_should_not_run
    )
    monkeypatch.setattr(read_ops, "read_execute", legacy_read_should_not_run)

    listed = await dispatcher.execute(
        "list_files",
        {
            "session_id": session.session_id,
            "path": ".",
            "recursive": False,
            "max_entries": 10,
        },
    )
    read = await dispatcher.execute(
        "read",
        {"session_id": session.session_id, "path": "demo.txt:1-2"},
    )

    assert any(entry.path == "demo.txt" for entry in listed.entries)
    assert read.kind == "file"
    assert read.content.endswith("1:alpha\n2:beta")
    assert read.file is not None
    assert read.file.session_id == session.session_id


@pytest.mark.asyncio
async def test_files_compatibility_facades_preserve_sessionless_local_calls(
    tmp_path, monkeypatch
):
    settings = _settings(tmp_path, monkeypatch)
    configure_runtime_services(settings)

    import local_shell_mcp.ops.files as files_ops

    markers = {
        name: object() for name in ("list", "write", "hash", "edit", "delete")
    }
    calls = []

    def fake_list(config, binding, path, recursive, max_entries):
        calls.append(("list", config, binding, path, recursive, max_entries))
        return markers["list"]

    def fake_write(config, binding, path, content, overwrite, expected_sha256):
        calls.append(
            (
                "write",
                config,
                binding,
                path,
                content,
                overwrite,
                expected_sha256,
            )
        )
        return markers["write"]

    def fake_hash(config, store, binding, input_text):
        calls.append(("hash", config, store, binding, input_text))
        return markers["hash"]

    def fake_edit(
        config,
        store,
        binding,
        path,
        start_line,
        end_line,
        replacement,
        snapshot_id,
    ):
        calls.append(
            (
                "edit",
                config,
                store,
                binding,
                path,
                start_line,
                end_line,
                replacement,
                snapshot_id,
            )
        )
        return markers["edit"]

    def fake_delete(config, binding, path, recursive):
        calls.append(("delete", config, binding, path, recursive))
        return markers["delete"]

    monkeypatch.setattr(files_ops, "_list_files_local", fake_list)
    monkeypatch.setattr(files_ops, "_write_file_local", fake_write)
    monkeypatch.setattr(files_ops, "_hashline_edit_local", fake_hash)
    monkeypatch.setattr(files_ops, "_edit_lines_local", fake_edit)
    monkeypatch.setattr(files_ops, "_delete_file_or_dir_local", fake_delete)

    assert (
        await files_ops.list_files_dispatch_execute("src", True, 7)
        is markers["list"]
    )
    assert (
        await files_ops.write_file_dispatch_execute(
            "a.txt", "alpha", False, expected_sha256="abc"
        )
        is markers["write"]
    )
    assert (
        await files_ops.hashline_edit_dispatch_execute("payload")
        is markers["hash"]
    )
    assert (
        await files_ops.edit_lines_dispatch_execute(
            "a.txt", 1, 2, "beta", snapshot_id="snap"
        )
        is markers["edit"]
    )
    assert (
        await files_ops.delete_file_or_dir_dispatch_execute("a.txt", True)
        is markers["delete"]
    )

    assert calls[0][2] is None
    assert calls[1][2] is None
    assert calls[2][3] is None
    assert calls[3][3] is None
    assert calls[4][2] is None


@pytest.mark.asyncio
async def test_files_compatibility_facades_preserve_local_session_routing(
    tmp_path, monkeypatch
):
    settings = _settings(tmp_path, monkeypatch)
    services = configure_runtime_services(settings)
    session = services.tool_session_store.create_session(workdir=tmp_path)

    import local_shell_mcp.ops.files as files_ops

    bindings = []

    def record_list(_config, binding, *_args):
        bindings.append(binding)
        return object()

    def record_write(_config, binding, *_args):
        bindings.append(binding)
        return object()

    def record_hash(_config, _store, binding, *_args):
        bindings.append(binding)
        return object()

    def record_edit(_config, _store, binding, *_args):
        bindings.append(binding)
        return object()

    def record_delete(_config, binding, *_args):
        bindings.append(binding)
        return object()

    monkeypatch.setattr(files_ops, "_list_files_local", record_list)
    monkeypatch.setattr(files_ops, "_write_file_local", record_write)
    monkeypatch.setattr(files_ops, "_hashline_edit_local", record_hash)
    monkeypatch.setattr(files_ops, "_edit_lines_local", record_edit)
    monkeypatch.setattr(files_ops, "_delete_file_or_dir_local", record_delete)

    await files_ops.list_files_dispatch_execute(session_id=session.session_id)
    await files_ops.write_file_dispatch_execute(
        "a.txt", "alpha", session_id=session.session_id
    )
    await files_ops.hashline_edit_dispatch_execute(
        "payload", session_id=session.session_id
    )
    await files_ops.edit_lines_dispatch_execute(
        "a.txt", 1, 1, "beta", session_id=session.session_id
    )
    await files_ops.delete_file_or_dir_dispatch_execute(
        "a.txt", session_id=session.session_id
    )

    assert len(bindings) == 5
    assert all(
        binding is not None and binding.target == "local"
        for binding in bindings
    )


@pytest.mark.asyncio
async def test_files_compatibility_facades_preserve_remote_session_routing(
    tmp_path, monkeypatch
):
    settings = _settings(tmp_path, monkeypatch)
    services = configure_runtime_services(settings)
    session = services.tool_session_store.create_session(
        target="remote",
        workdir="/remote/work",
        machine="worker-a",
        worker_session_id="WORKER01",
    )

    import local_shell_mcp.ops.files as files_ops

    calls = []
    context = {"path": "a.txt", "bytes": 0, "content": ""}
    responses = {
        "list_files": {
            "limit_count": 7,
            "count": 0,
            "is_truncated": False,
            "entries": [],
        },
        "write_file": {"path": "a.txt", "bytes": 5, "created": True},
        "hashline_edit": {
            "path": "a.txt",
            "start_line": 1,
            "end_line": 1,
            "replacement_line_count": 1,
            "diff": "",
            "context": context,
            "hunk_count": 1,
            "hunks": [
                {
                    "path": "a.txt",
                    "start_line": 1,
                    "end_line": 1,
                    "replacement_line_count": 1,
                    "context": context,
                }
            ],
        },
        "edit_lines": {
            "path": "a.txt",
            "start_line": 1,
            "end_line": 1,
            "replacement_line_count": 1,
            "diff": "",
            "context": context,
        },
        "delete_file_or_dir": {"path": "a.txt", "deleted": "file"},
    }

    async def fake_remote(binding, tool, args):
        calls.append((binding, tool, args))
        return responses[tool]

    monkeypatch.setattr(files_ops, "call_remote_session_tool", fake_remote)

    listed = await files_ops.list_files_dispatch_execute(
        "src", False, 7, session.session_id
    )
    written = await files_ops.write_file_dispatch_execute(
        "a.txt", "alpha", True, session.session_id, "abc"
    )
    hashed = await files_ops.hashline_edit_dispatch_execute(
        "payload", session.session_id
    )
    edited = await files_ops.edit_lines_dispatch_execute(
        "a.txt", 1, 1, "beta", "snap", session.session_id
    )
    deleted = await files_ops.delete_file_or_dir_dispatch_execute(
        "a.txt", True, session.session_id
    )

    assert listed.count == 0
    assert written.created is True
    assert hashed.hunk_count == 1
    assert edited.replacement_line_count == 1
    assert deleted.deleted == "file"
    assert [tool for _binding, tool, _args in calls] == [
        "list_files",
        "write_file",
        "hashline_edit",
        "edit_lines",
        "delete_file_or_dir",
    ]
    assert all(binding.machine == "worker-a" for binding, _tool, _args in calls)


@pytest.mark.asyncio
async def test_registry_compatibility_functions_keep_legacy_delegation(
    monkeypatch,
):
    calls = []

    async def fake_list(*args):
        calls.append(("list", args))
        return "list"

    async def fake_write(*args):
        calls.append(("write", args))
        return "write"

    async def fake_edit(*args):
        calls.append(("edit", args))
        return "edit"

    async def fake_hash(*args):
        calls.append(("hash", args))
        return "hash"

    async def fake_delete(*args):
        calls.append(("delete", args))
        return "delete"

    async def fake_read(*args):
        calls.append(("read", args))
        return "read"

    monkeypatch.setattr(
        files_registry_module, "list_files_dispatch_execute", fake_list
    )
    monkeypatch.setattr(
        files_registry_module, "write_file_dispatch_execute", fake_write
    )
    monkeypatch.setattr(
        files_registry_module, "edit_lines_dispatch_execute", fake_edit
    )
    monkeypatch.setattr(
        files_registry_module, "hashline_edit_dispatch_execute", fake_hash
    )
    monkeypatch.setattr(
        files_registry_module,
        "delete_file_or_dir_dispatch_execute",
        fake_delete,
    )
    monkeypatch.setattr(read_registry_module, "read_execute", fake_read)

    assert (
        await files_registry_module.list_files.func("SESSION1", "src", True, 7)
        == "list"
    )
    assert (
        await files_registry_module.write_file.func(
            "SESSION1", "a.txt", "alpha", False
        )
        == "write"
    )
    assert (
        await files_registry_module.edit_lines.func(
            "a.txt", 1, 2, "beta", "SESSION1", "snap"
        )
        == "edit"
    )
    assert (
        await files_registry_module.hashline_edit.func("SESSION1", "payload")
        == "hash"
    )
    assert (
        await files_registry_module.delete_file_or_dir.func(
            "SESSION1", "a.txt", True
        )
        == "delete"
    )
    assert await read_registry_module.read.func("SESSION1", "a.txt") == "read"
    assert [name for name, _args in calls] == [
        "list",
        "write",
        "edit",
        "hash",
        "delete",
        "read",
    ]


@pytest.mark.asyncio
async def test_bound_file_registry_handlers_delegate_to_injected_service(
    tmp_path, monkeypatch
):
    settings = _settings(tmp_path, monkeypatch)
    services = configure_runtime_services(settings)
    catalog = build_controller_tool_catalog(
        settings,
        services.tool_session_store,
        RemoteManager(lambda: settings, state_store=services.state_store),
    )
    registry = _registry(catalog, FileToolRegistry)
    service = registry._files_service
    assert service is not None
    calls = []

    async def fake_write(*args):
        calls.append(("write", args))
        return "write"

    async def fake_edit(*args):
        calls.append(("edit", args))
        return "edit"

    async def fake_hash(*args):
        calls.append(("hash", args))
        return "hash"

    async def fake_delete(*args):
        calls.append(("delete", args))
        return "delete"

    monkeypatch.setattr(service, "write_file", fake_write)
    monkeypatch.setattr(service, "edit_lines", fake_edit)
    monkeypatch.setattr(service, "hashline_edit", fake_hash)
    monkeypatch.setattr(service, "delete_file_or_dir", fake_delete)

    assert (
        await registry._bound_write_file("SESSION1", "a.txt", "alpha", False)
        == "write"
    )
    assert (
        await registry._bound_edit_lines(
            "a.txt", 1, 2, "beta", "SESSION1", "snap"
        )
        == "edit"
    )
    assert await registry._bound_hashline_edit("SESSION1", "payload") == "hash"
    assert (
        await registry._bound_delete_file_or_dir("SESSION1", "a.txt", True)
        == "delete"
    )
    assert [name for name, _args in calls] == [
        "write",
        "edit",
        "hash",
        "delete",
    ]


@pytest.mark.asyncio
async def test_unbound_registries_reject_direct_bound_handler_use() -> None:
    file_registry = FileToolRegistry()

    with pytest.raises(RuntimeError, match="Files service is not bound"):
        file_registry._require_service()

    read_registry = ReadToolRegistry()
    with pytest.raises(RuntimeError, match="Files service is not bound"):
        await read_registry._bound_read("SESSION1", "a.txt")
