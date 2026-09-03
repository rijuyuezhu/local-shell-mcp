import time

import pytest

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.tool_session import store as store_module
from local_shell_mcp.tool_session.bindings import (
    LocalSessionBinding,
    RemoteSessionBinding,
)
from local_shell_mcp.tool_session.resolver import SessionResolver
from local_shell_mcp.tool_session.store import (
    ExpiredAgentSessionError,
    SessionTerminationRequestedError,
)


def _store(tmp_path, monkeypatch) -> store_module.ToolSessionStore:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    clear_settings_cache()
    store = store_module.ToolSessionStore()
    store.clear()
    return store


def test_admit_tool_sessions_checks_every_session_before_refreshing_any(
    tmp_path, monkeypatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    first = store.create_session(workdir=tmp_path)
    second = store.create_session(workdir=tmp_path)
    store.request_termination(second.session_id)
    first_before = store.require_session(first.session_id)

    with pytest.raises(SessionTerminationRequestedError) as exc_info:
        store.admit_tool_sessions((first.session_id, second.session_id))

    assert exc_info.value.session_id == second.session_id
    assert (
        store.require_session(first.session_id).updated_at
        == first_before.updated_at
    )


def test_touch_session_remains_mechanism_not_admission_authority(
    tmp_path, monkeypatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    session = store.create_session(workdir=tmp_path)
    store.request_termination(session.session_id)

    touched = store.touch_session(session.session_id)

    assert touched.termination_requested_at is not None
    with pytest.raises(SessionTerminationRequestedError):
        store.admit_active_session(session.session_id)


def test_admit_active_session_does_not_reenter_touch_after_validation(
    tmp_path, monkeypatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    session = store.create_session(workdir=tmp_path)
    original_touch = store.touch_session

    def terminate_before_touch(session_id: str):
        store.request_termination(session_id)
        return original_touch(session_id)

    monkeypatch.setattr(store, "touch_session", terminate_before_touch)

    admitted = store.admit_active_session(session.session_id)

    assert admitted.termination_requested_at is None
    assert (
        store.require_session(session.session_id).termination_requested_at
        is None
    )


def test_generic_enforcement_delegates_to_store_admission(
    monkeypatch,
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    class FakeStore:
        def admit_tool_sessions(self, session_ids: tuple[str, ...]) -> None:
            calls.append(("active", session_ids))

        def require_cleanup_sessions(
            self, session_ids: tuple[str, ...]
        ) -> None:
            calls.append(("cleanup", session_ids))

    monkeypatch.setattr(store_module, "get_tool_session_store", FakeStore)

    store_module.enforce_tool_session_control({"session_id": "SESSION1"})
    store_module.enforce_tool_session_control(
        {"session_id": "SESSION2"}, termination_cleanup=True
    )

    assert calls == [
        ("active", ("SESSION1",)),
        ("cleanup", ("SESSION2",)),
    ]


def test_resolver_reads_fresh_workdir_for_each_operation(
    tmp_path, monkeypatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    first_workdir = tmp_path / "first"
    second_workdir = tmp_path / "second"
    first_workdir.mkdir()
    second_workdir.mkdir()
    session = store.create_session(workdir=first_workdir)
    resolver = SessionResolver(store)

    first_binding = resolver.resolve_active_binding(session.session_id)
    store.change_session_workdir(session.session_id, second_workdir)
    second_binding = resolver.resolve_active_binding(session.session_id)

    assert first_binding == LocalSessionBinding(
        session_id=session.session_id, workdir=str(first_workdir.resolve())
    )
    assert second_binding == LocalSessionBinding(
        session_id=session.session_id, workdir=str(second_workdir.resolve())
    )
    assert first_binding is not second_binding


def test_resolver_active_path_preserves_expiry_policy(
    tmp_path, monkeypatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    session = store.create_session(workdir=tmp_path, expires_at=time.time() - 1)

    with pytest.raises(ExpiredAgentSessionError):
        SessionResolver(store).resolve_active_binding(session.session_id)


def test_resolver_cleanup_path_keeps_expired_remote_binding(
    tmp_path, monkeypatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    session = store.create_session(
        target="remote",
        workdir="/remote/work",
        machine="worker-a",
        worker_session_id="WORKER12",
        expires_at=time.time() - 1,
    )

    binding = SessionResolver(store).prepare_cleanup_binding(session.session_id)

    assert binding == RemoteSessionBinding(
        session_id=session.session_id,
        workdir="/remote/work",
        machine="worker-a",
        worker_session_id="WORKER12",
    )
    prepared = store.require_session(session.session_id)
    assert prepared.expires_at is None
    assert prepared.termination_requested_at is not None
