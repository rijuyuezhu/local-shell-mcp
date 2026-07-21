from __future__ import annotations

import json
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import local_shell_mcp.server.http.ui_remote_files as remote_files_module
import local_shell_mcp.server.http.ui_todos as ui_todos_module
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.oauth.core.scopes import (
    SCOPE_REMOTE_USE,
    SCOPE_SHELL_READ,
    SCOPE_SHELL_WRITE,
)
from local_shell_mcp.oauth.protocol.token_codec import issue_access_token
from local_shell_mcp.ops.todo import (
    TodoConflictError,
    read_todos_execute,
    write_todos_execute,
)
from local_shell_mcp.schemas.result_models.remote import (
    RemoteListMachinesOutput,
    RemoteMachineInfo,
)
from local_shell_mcp.server.http.app import build_http_app
from local_shell_mcp.tool_session.store import get_tool_session_store

BASE_URL = "https://local-shell-mcp.example"


@pytest.fixture(autouse=True)
def _reset_state():
    clear_settings_cache()
    get_tool_session_store().clear()
    ui_todos_module.clear_ui_todo_sessions()
    remote_files_module.clear_ui_remote_file_sessions()
    yield
    clear_settings_cache()
    get_tool_session_store().clear()
    ui_todos_module.clear_ui_todo_sessions()
    remote_files_module.clear_ui_remote_file_sessions()


def _configure(
    monkeypatch,
    workspace,
    *,
    auth_mode: str = "none",
    remote_enabled: bool = False,
    max_todos: int | None = None,
) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(workspace / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", auth_mode)
    monkeypatch.setenv("LOCAL_SHELL_MCP_BASE_URL", BASE_URL)
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_REMOTE_ENABLED", "true" if remote_enabled else "false"
    )
    if max_todos is not None:
        monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_TODOS", str(max_todos))
    clear_settings_cache()


def _client(monkeypatch, tmp_path, *, auth_mode: str = "none") -> TestClient:
    _configure(monkeypatch, tmp_path / "workspace", auth_mode=auth_mode)
    return TestClient(
        build_http_app(),
        base_url=BASE_URL,
        client=("203.0.113.14", 50004),
    )


def _token(scope: str) -> str:
    return issue_access_token(
        client_id="webui-todos-test",
        scope=scope,
        resource=f"{BASE_URL}/mcp",
    )


def _item(identifier: str, content: str = "ship it") -> dict[str, str]:
    return {
        "id": identifier,
        "content": content,
        "status": "pending",
        "priority": "high",
    }


def test_local_todos_revision_guard_and_atomic_persistence(
    monkeypatch, tmp_path
):
    client = _client(monkeypatch, tmp_path)

    initial = client.get("/api/ui/todos")
    saved = client.put(
        "/api/ui/todos",
        json={
            "machine": "local",
            "expected_revision": 0,
            "todos": [_item("one")],
        },
    )
    stale = client.put(
        "/api/ui/todos",
        json={
            "machine": "local",
            "expected_revision": 0,
            "todos": [_item("stale", "must not win")],
        },
    )
    current = client.get("/api/ui/todos", params={"machine": "local"})

    assert initial.status_code == 200
    assert initial.json()["data"]["revision"] == 0
    assert initial.json()["data"]["todos"] == []
    assert saved.status_code == 200
    assert saved.json()["data"]["revision"] == 1
    assert stale.status_code == 409
    assert stale.json()["error"] == "TodoConflictError"
    assert current.json()["data"]["revision"] == 1
    assert current.json()["data"]["todos"][0]["id"] == "one"

    todo_files = list(
        (tmp_path / "workspace" / ".state" / "todos").glob("*.json")
    )
    assert len(todo_files) == 1
    assert stat.S_IMODE(todo_files[0].stat().st_mode) == 0o600
    assert not list(todo_files[0].parent.glob("*.tmp"))


def test_todo_api_validates_shape_count_ids_and_encoded_lengths(
    monkeypatch, tmp_path
):
    workspace = tmp_path / "workspace"
    _configure(monkeypatch, workspace, max_todos=2)
    client = TestClient(build_http_app(), base_url=BASE_URL)

    not_array = client.put(
        "/api/ui/todos",
        json={"expected_revision": 0, "todos": {}},
    )
    too_many = client.put(
        "/api/ui/todos",
        json={
            "expected_revision": 0,
            "todos": [_item("a"), _item("b"), _item("c")],
        },
    )
    duplicate = client.put(
        "/api/ui/todos",
        json={"expected_revision": 0, "todos": [_item("same"), _item("same")]},
    )
    long_content = client.put(
        "/api/ui/todos",
        json={
            "expected_revision": 0,
            "todos": [_item("a", "é" * 8_193)],
        },
    )
    bad_revision = client.put(
        "/api/ui/todos",
        json={"expected_revision": True, "todos": []},
    )

    assert not_array.status_code == 400
    assert "JSON array" in not_array.text
    assert too_many.status_code == 400
    assert "max is 2" in too_many.text
    assert duplicate.status_code == 400
    assert "duplicate todo id" in duplicate.text
    assert long_content.status_code == 400
    assert "encoded bytes" in long_content.text
    assert bad_revision.status_code == 400
    assert "non-negative integer" in bad_revision.text


def test_legacy_todo_payload_reads_as_revision_zero(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    _configure(monkeypatch, workspace)
    session = get_tool_session_store().create_session(
        target="local", workdir=str(workspace), label="legacy"
    )
    path = workspace / ".state" / "todos" / f"{session.session_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"updated_at": 1.0, "todos": [_item("legacy")]}),
        encoding="utf-8",
    )

    result = read_todos_execute(session.session_id)

    assert result.revision == 0
    assert result.todos[0].id == "legacy"


def test_revision_guard_serializes_concurrent_replacements(
    monkeypatch, tmp_path
):
    workspace = tmp_path / "workspace"
    _configure(monkeypatch, workspace)
    session = get_tool_session_store().create_session(
        target="local", workdir=str(workspace), label="concurrency"
    )

    def replace(identifier: str):
        try:
            return write_todos_execute(
                [_item(identifier)], session.session_id, expected_revision=0
            )
        except TodoConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(replace, ["first", "second"]))

    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, TodoConflictError) for result in results) == 1
    current = read_todos_execute(session.session_id)
    assert current.revision == 1
    assert current.todos[0].id in {"first", "second"}


def test_local_ui_reuses_one_explicit_workspace_session(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    store = get_tool_session_store()
    created = []
    original_create_session = store.create_session

    def create_session(**kwargs):  # noqa: ANN003, ANN202
        session = original_create_session(**kwargs)
        created.append(session)
        return session

    monkeypatch.setattr(store, "create_session", create_session)

    assert client.get("/api/ui/todos").status_code == 200
    assert client.get("/api/ui/todos").status_code == 200
    assert (
        client.put(
            "/api/ui/todos",
            json={"expected_revision": 0, "todos": [_item("one")]},
        ).status_code
        == 200
    )

    assert len(created) == 1
    assert created[0].label == "Human UI Workspace"
    assert created[0].target == "local"


class _FakeManager:
    def __init__(self, status: str = "online") -> None:
        self.status = status

    def list_machines(self) -> RemoteListMachinesOutput:
        return RemoteListMachinesOutput(
            machines=[
                RemoteMachineInfo(
                    name="edge",
                    status=self.status,
                    workdir="/srv/workspace",
                    last_seen=1.0,
                    queue_depth=0,
                    capabilities=["todos"],
                    info={},
                )
            ],
            counts={self.status: 1, "total": 1},
        )


class _FakeRemoteTodos:
    def __init__(self) -> None:
        self.started: list[dict[str, Any]] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.sessions: dict[str, dict[str, Any]] = {}
        self.next_session = 1
        self.stale_once = False
        self.malformed = False

    async def start_session(self, **kwargs):  # noqa: ANN003, ANN201
        self.started.append(dict(kwargs))
        session_id = f"remote-ui-{self.next_session}"
        self.next_session += 1
        self.sessions[session_id] = {
            "revision": 0,
            "updated_at": None,
            "todos": [],
        }
        return {"session_id": session_id, "workdir": kwargs["workdir"]}

    async def call(
        self,
        machine: str,
        tool: str,
        args: dict[str, Any],
        timeout_s: int,
    ) -> dict[str, Any]:
        assert machine == "edge"
        assert 1 <= timeout_s <= 60
        self.calls.append((tool, dict(args)))
        if self.stale_once:
            self.stale_once = False
            return {
                "ok": True,
                "data": {
                    "status": "error",
                    "error_type": "ValueError",
                    "message": "Unknown session_id: stale",
                },
            }
        session_id = str(args["session_id"])
        assert session_id in self.sessions
        if self.malformed:
            return {"ok": True, "data": {"revision": "bad", "todos": {}}}
        state = self.sessions[session_id]
        if tool == "read_todos":
            return {"ok": True, "data": dict(state)}
        assert tool == "write_todos"
        expected = args.get("expected_revision")
        revision = int(state["revision"])
        if expected != revision:
            return {
                "ok": True,
                "data": {
                    "status": "error",
                    "error_type": "TodoConflictError",
                    "message": (
                        f"Todo list changed from revision {expected} to {revision}; "
                        "reload before saving"
                    ),
                },
            }
        state = {
            "revision": revision + 1,
            "updated_at": 2.0,
            "todos": list(args.get("todos") or []),
        }
        self.sessions[session_id] = state
        return {"ok": True, "data": dict(state)}


def _remote_client(
    monkeypatch,
    tmp_path,
    fake: _FakeRemoteTodos,
    *,
    auth_mode: str = "none",
    status: str = "online",
) -> TestClient:
    _configure(
        monkeypatch,
        tmp_path / "workspace",
        auth_mode=auth_mode,
        remote_enabled=True,
    )
    monkeypatch.setattr(
        remote_files_module,
        "remote_manager",
        lambda: _FakeManager(status=status),
    )
    monkeypatch.setattr(
        remote_files_module, "start_worker_session", fake.start_session
    )
    monkeypatch.setattr(
        remote_files_module, "call_remote_worker_tool", fake.call
    )
    return TestClient(
        build_http_app(),
        base_url=BASE_URL,
        client=("203.0.113.14", 50004),
    )


def test_remote_todos_are_isolated_and_reuse_machine_workspace_session(
    monkeypatch, tmp_path
):
    fake = _FakeRemoteTodos()
    client = _remote_client(monkeypatch, tmp_path, fake)

    remote_initial = client.get("/api/ui/todos", params={"machine": "edge"})
    remote_saved = client.put(
        "/api/ui/todos",
        json={
            "machine": "edge",
            "expected_revision": 0,
            "todos": [_item("remote")],
        },
    )
    remote_current = client.get("/api/ui/todos", params={"machine": "edge"})
    local_current = client.get("/api/ui/todos", params={"machine": "local"})

    assert remote_initial.status_code == 200
    assert remote_saved.status_code == 200
    assert remote_saved.json()["data"]["revision"] == 1
    assert remote_current.json()["data"]["todos"][0]["id"] == "remote"
    assert local_current.json()["data"]["todos"] == []
    assert len(fake.started) == 1
    assert fake.started[0]["label"] == "Human UI Workspace"
    assert {call[1]["session_id"] for call in fake.calls} == {"remote-ui-1"}


def test_remote_todos_recreate_stale_worker_session_once(monkeypatch, tmp_path):
    fake = _FakeRemoteTodos()
    client = _remote_client(monkeypatch, tmp_path, fake)
    assert (
        client.get("/api/ui/todos", params={"machine": "edge"}).status_code
        == 200
    )

    fake.stale_once = True
    recreated = client.get("/api/ui/todos", params={"machine": "edge"})

    assert recreated.status_code == 200
    assert recreated.json()["data"]["revision"] == 0
    assert len(fake.started) == 2
    assert fake.calls[-1][1]["session_id"] == "remote-ui-2"


def test_remote_todos_map_conflict_malformed_and_offline_results(
    monkeypatch, tmp_path
):
    fake = _FakeRemoteTodos()
    client = _remote_client(monkeypatch, tmp_path, fake)
    assert (
        client.put(
            "/api/ui/todos",
            json={
                "machine": "edge",
                "expected_revision": 0,
                "todos": [_item("remote")],
            },
        ).status_code
        == 200
    )

    conflict = client.put(
        "/api/ui/todos",
        json={
            "machine": "edge",
            "expected_revision": 0,
            "todos": [_item("stale")],
        },
    )
    fake.malformed = True
    malformed = client.get("/api/ui/todos", params={"machine": "edge"})

    assert conflict.status_code == 409
    assert conflict.json()["error"] == "TodoConflictError"
    assert malformed.status_code == 502
    assert "malformed todo state" in malformed.text

    offline_fake = _FakeRemoteTodos()
    offline_client = _remote_client(
        monkeypatch, tmp_path / "offline", offline_fake, status="offline"
    )
    offline = offline_client.get("/api/ui/todos", params={"machine": "edge"})
    assert offline.status_code == 503
    assert "offline" in offline.text
    assert offline_fake.started == []


def test_todo_api_enforces_local_remote_and_write_scopes(monkeypatch, tmp_path):
    fake = _FakeRemoteTodos()
    client = _remote_client(monkeypatch, tmp_path, fake, auth_mode="oauth")
    read_only = {"Authorization": f"Bearer {_token(SCOPE_SHELL_READ)}"}
    local_full = {
        "Authorization": f"Bearer {_token(f'{SCOPE_SHELL_READ} {SCOPE_SHELL_WRITE}')}"
    }
    remote_read = {
        "Authorization": f"Bearer {_token(f'{SCOPE_SHELL_READ} {SCOPE_REMOTE_USE}')}"
    }
    remote_full = {
        "Authorization": f"Bearer {_token(f'{SCOPE_SHELL_READ} {SCOPE_SHELL_WRITE} {SCOPE_REMOTE_USE}')}"
    }

    assert client.get("/api/ui/todos", headers=read_only).status_code == 200
    missing_local_write = client.put(
        "/api/ui/todos",
        json={"expected_revision": 0, "todos": []},
        headers=read_only,
    )
    missing_remote = client.get(
        "/api/ui/todos", params={"machine": "edge"}, headers=read_only
    )
    readable_remote = client.get(
        "/api/ui/todos", params={"machine": "edge"}, headers=remote_read
    )
    missing_remote_write = client.put(
        "/api/ui/todos",
        json={"machine": "edge", "expected_revision": 0, "todos": []},
        headers=remote_read,
    )
    writable_local = client.put(
        "/api/ui/todos",
        json={"expected_revision": 0, "todos": []},
        headers=local_full,
    )
    writable_remote = client.put(
        "/api/ui/todos",
        json={"machine": "edge", "expected_revision": 0, "todos": []},
        headers=remote_full,
    )

    assert missing_local_write.status_code == 403
    assert SCOPE_SHELL_WRITE in missing_local_write.text
    assert missing_remote.status_code == 403
    assert SCOPE_REMOTE_USE in missing_remote.text
    assert readable_remote.status_code == 200
    assert missing_remote_write.status_code == 403
    assert SCOPE_SHELL_WRITE in missing_remote_write.text
    assert writable_local.status_code == 200
    assert writable_remote.status_code == 200


def test_todo_static_ui_has_machine_isolation_and_stale_write_guards():
    static_root = (
        Path(__file__).parents[1] / "src" / "local_shell_mcp" / "ui_static"
    )
    index = (static_root / "index.html").read_text(encoding="utf-8")
    script = (static_root / "web.js").read_text(encoding="utf-8")

    assert 'id="todo-machine"' in index
    assert 'id="todo-save"' in index
    assert "todoGeneration" in script
    assert "expected_revision" in script
    assert "todoMutationBusy" in script
    assert "Todo list changed elsewhere; reloaded the latest revision" in script
