import asyncio

import pytest

import local_shell_mcp.composition.services as composition_services
from local_shell_mcp.composition.services import (
    build_runtime_services,
    install_runtime_services,
)
from local_shell_mcp.config.settings import Settings
from local_shell_mcp.executors.runtime import build_controller_runtime
from local_shell_mcp.executors.runtime_services import (
    configure_runtime_services,
)
from local_shell_mcp.persistence import (
    FileStateStore,
    configure_state_store,
    get_state_store,
)
from local_shell_mcp.remote.manager import (
    RemoteManager,
    configure_remote_manager,
    remote_manager,
)
from local_shell_mcp.remote_worker.runtime_composition import (
    build_worker_runtime,
)
from local_shell_mcp.tool_session import (
    configure_tool_session_store,
    get_tool_session_store,
)
from local_shell_mcp.tool_session.store import ToolSessionStore


def test_runtime_services_install_explicit_store_dependencies(tmp_path):
    settings = Settings(
        workspace_root=tmp_path,
        state_dir=tmp_path / ".state",
    )

    services = configure_runtime_services(settings)
    try:
        assert get_state_store() is services.state_store
        assert get_tool_session_store() is services.tool_session_store
        assert services.state_store.layout.root == settings.state_dir
        assert services.tool_session_store._settings() is settings
    finally:
        configure_tool_session_store(None)
        configure_state_store(None)


def test_runtime_service_construction_does_not_install_compatibility_globals(
    tmp_path,
):
    outer_settings = Settings(
        workspace_root=tmp_path,
        state_dir=tmp_path / "outer-state",
    )
    outer_state_store = FileStateStore(lambda: outer_settings.state_dir)
    outer_session_store = ToolSessionStore(
        state_store=outer_state_store,
        settings_provider=lambda: outer_settings,
    )
    configure_state_store(outer_state_store)
    configure_tool_session_store(outer_session_store)
    settings = Settings(
        workspace_root=tmp_path,
        state_dir=tmp_path / "runtime-state",
    )
    try:
        services = build_runtime_services(settings)

        assert services.state_store is not outer_state_store
        assert services.tool_session_store is not outer_session_store
        assert get_state_store() is outer_state_store
        assert get_tool_session_store() is outer_session_store
    finally:
        configure_tool_session_store(None)
        configure_state_store(None)


@pytest.mark.asyncio
async def test_controller_runtime_lifespan_restores_outer_compatibility_bindings(
    tmp_path,
):
    outer_settings = Settings(
        workspace_root=tmp_path,
        state_dir=tmp_path / "outer-state",
    )
    outer_state_store = FileStateStore(lambda: outer_settings.state_dir)
    outer_session_store = ToolSessionStore(
        state_store=outer_state_store,
        settings_provider=lambda: outer_settings,
    )
    configure_state_store(outer_state_store)
    configure_tool_session_store(outer_session_store)
    runtime = build_controller_runtime(
        Settings(
            workspace_root=tmp_path,
            state_dir=tmp_path / "controller-state",
        )
    )
    try:
        assert get_state_store() is outer_state_store
        assert get_tool_session_store() is outer_session_store

        async with runtime.lifespan() as active:
            assert active is runtime
            assert get_state_store() is runtime.services.state_store
            assert (
                get_tool_session_store() is runtime.services.tool_session_store
            )

        assert get_state_store() is outer_state_store
        assert get_tool_session_store() is outer_session_store
        await runtime.aclose()
        assert get_state_store() is outer_state_store
        assert get_tool_session_store() is outer_session_store
        with pytest.raises(RuntimeError, match="cannot be restarted"):
            await runtime.start()
    finally:
        configure_tool_session_store(None)
        configure_state_store(None)


@pytest.mark.asyncio
async def test_worker_runtime_lifespan_restores_bindings_after_exception(
    tmp_path,
):
    outer_settings = Settings(
        workspace_root=tmp_path,
        state_dir=tmp_path / "outer-state",
    )
    outer_state_store = FileStateStore(lambda: outer_settings.state_dir)
    outer_session_store = ToolSessionStore(
        state_store=outer_state_store,
        settings_provider=lambda: outer_settings,
    )
    configure_state_store(outer_state_store)
    configure_tool_session_store(outer_session_store)
    runtime = build_worker_runtime(
        Settings(
            workspace_root=tmp_path,
            state_dir=tmp_path / "worker-state",
        )
    )
    try:
        with pytest.raises(RuntimeError, match="boom"):
            async with runtime.lifespan():
                assert get_state_store() is runtime.services.state_store
                assert (
                    get_tool_session_store()
                    is runtime.services.tool_session_store
                )
                raise RuntimeError("boom")

        assert get_state_store() is outer_state_store
        assert get_tool_session_store() is outer_session_store
        await runtime.aclose()
    finally:
        configure_tool_session_store(None)
        configure_state_store(None)


def test_runtime_service_installation_rolls_back_partial_startup(
    tmp_path, monkeypatch
):
    settings = Settings(
        workspace_root=tmp_path,
        state_dir=tmp_path / "runtime-state",
    )
    outer_state_store = FileStateStore(lambda: tmp_path / "outer-state")
    outer_session_store = ToolSessionStore(
        state_store=outer_state_store,
        settings_provider=lambda: settings,
    )
    configure_state_store(outer_state_store)
    configure_tool_session_store(outer_session_store)
    services = build_runtime_services(settings)

    def fail_session_install(_store):
        raise RuntimeError("session install failed")

    monkeypatch.setattr(
        composition_services,
        "configure_tool_session_store",
        fail_session_install,
    )
    try:
        with pytest.raises(RuntimeError, match="session install failed"):
            install_runtime_services(services)

        assert get_state_store() is outer_state_store
        assert get_tool_session_store() is outer_session_store
    finally:
        monkeypatch.undo()
        configure_tool_session_store(None)
        configure_state_store(None)


@pytest.mark.asyncio
async def test_controller_runtime_startup_failure_closes_started_bindings(
    tmp_path, monkeypatch
):
    outer_settings = Settings(
        workspace_root=tmp_path,
        state_dir=tmp_path / "outer-state",
    )
    outer_state_store = FileStateStore(lambda: outer_settings.state_dir)
    outer_session_store = ToolSessionStore(
        state_store=outer_state_store,
        settings_provider=lambda: outer_settings,
    )
    configure_state_store(outer_state_store)
    configure_tool_session_store(outer_session_store)
    runtime = build_controller_runtime(
        Settings(
            workspace_root=tmp_path,
            state_dir=tmp_path / "controller-state",
        )
    )
    original_start = runtime.start

    async def fail_after_start() -> None:
        await original_start()
        raise RuntimeError("startup failed")

    monkeypatch.setattr(runtime, "start", fail_after_start)
    try:
        with pytest.raises(RuntimeError, match="startup failed"):
            async with runtime.lifespan():
                pytest.fail("startup failure must prevent entering the body")

        assert get_state_store() is outer_state_store
        assert get_tool_session_store() is outer_session_store
    finally:
        configure_tool_session_store(None)
        configure_state_store(None)


@pytest.mark.asyncio
async def test_controller_runtime_remote_binding_failure_closes_remote_manager(
    tmp_path, monkeypatch
):
    outer_settings = Settings(
        workspace_root=tmp_path,
        state_dir=tmp_path / "outer-state",
    )
    outer_state_store = FileStateStore(lambda: outer_settings.state_dir)
    outer_session_store = ToolSessionStore(
        state_store=outer_state_store,
        settings_provider=lambda: outer_settings,
    )
    configure_state_store(outer_state_store)
    configure_tool_session_store(outer_session_store)
    runtime = build_controller_runtime(
        Settings(
            workspace_root=tmp_path,
            state_dir=tmp_path / "controller-state",
        )
    )

    def fail_remote_binding(_manager):
        raise RuntimeError("remote binding failed")

    monkeypatch.setattr(
        "local_shell_mcp.executors.runtime.configure_remote_manager",
        fail_remote_binding,
    )
    try:
        with pytest.raises(RuntimeError, match="remote binding failed"):
            await runtime.start()

        assert runtime.remote_manager._closed is True
        assert get_state_store() is outer_state_store
        assert get_tool_session_store() is outer_session_store
    finally:
        configure_tool_session_store(None)
        configure_state_store(None)


@pytest.mark.asyncio
async def test_worker_runtime_cancellation_closes_bindings(tmp_path):
    outer_settings = Settings(
        workspace_root=tmp_path,
        state_dir=tmp_path / "outer-state",
    )
    outer_state_store = FileStateStore(lambda: outer_settings.state_dir)
    outer_session_store = ToolSessionStore(
        state_store=outer_state_store,
        settings_provider=lambda: outer_settings,
    )
    configure_state_store(outer_state_store)
    configure_tool_session_store(outer_session_store)
    runtime = build_worker_runtime(
        Settings(
            workspace_root=tmp_path,
            state_dir=tmp_path / "worker-state",
        )
    )
    entered = asyncio.Event()

    async def run_until_cancelled() -> None:
        async with runtime.lifespan():
            entered.set()
            await asyncio.Event().wait()

    try:
        task = asyncio.create_task(run_until_cancelled())
        await entered.wait()
        assert get_state_store() is runtime.services.state_store
        assert get_tool_session_store() is runtime.services.tool_session_store

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert get_state_store() is outer_state_store
        assert get_tool_session_store() is outer_session_store
    finally:
        configure_tool_session_store(None)
        configure_state_store(None)


@pytest.mark.asyncio
async def test_controller_runtime_owns_and_restores_remote_manager_binding(
    tmp_path,
):
    outer_settings = Settings(
        workspace_root=tmp_path,
        state_dir=tmp_path / "outer-state",
    )
    outer_state_store = FileStateStore(lambda: outer_settings.state_dir)
    outer_manager = RemoteManager(
        lambda: outer_settings,
        state_store=outer_state_store,
    )
    configure_remote_manager(outer_manager)
    runtime = build_controller_runtime(
        Settings(
            workspace_root=tmp_path,
            state_dir=tmp_path / "controller-state",
        )
    )
    try:
        assert remote_manager() is outer_manager
        async with runtime.lifespan():
            assert remote_manager() is runtime.remote_manager
            assert runtime.remote_manager._loop is asyncio.get_running_loop()

        assert remote_manager() is outer_manager
        assert runtime.remote_manager._closed is True
    finally:
        configure_remote_manager(None)
