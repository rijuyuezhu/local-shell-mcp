from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import local_shell_mcp.server.http.ui_remotes as remotes_module
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.oauth.core.scopes import SCOPE_REMOTE_USE, SCOPE_SHELL_READ
from local_shell_mcp.oauth.protocol.token_codec import issue_access_token
from local_shell_mcp.schemas.result_models.remote import (
    RemoteInviteOutput,
    RemoteListMachinesOutput,
    RemoteMachineInfo,
    RemoteRenameMachineOutput,
    RemoteRevokeMachineOutput,
)
from local_shell_mcp.server.http.app import build_http_app

BASE_URL = "https://local-shell-mcp.example"


@pytest.fixture(autouse=True)
def _reset_settings():
    clear_settings_cache()
    yield
    clear_settings_cache()


def _configure(
    monkeypatch,
    workspace: Path,
    *,
    auth_mode: str = "none",
    remote_enabled: bool = True,
) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(workspace / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", auth_mode)
    monkeypatch.setenv("LOCAL_SHELL_MCP_BASE_URL", BASE_URL)
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_REMOTE_ENABLED",
        "true" if remote_enabled else "false",
    )
    clear_settings_cache()


def _client(
    monkeypatch,
    tmp_path: Path,
    *,
    auth_mode: str = "none",
    remote_enabled: bool = True,
) -> TestClient:
    _configure(
        monkeypatch,
        tmp_path / "workspace",
        auth_mode=auth_mode,
        remote_enabled=remote_enabled,
    )
    return TestClient(
        build_http_app(),
        base_url=BASE_URL,
        client=("203.0.113.15", 50006),
    )


def _headers(scope: str) -> dict[str, str]:
    token = issue_access_token(
        client_id="webui-remotes-test",
        scope=scope,
        resource=f"{BASE_URL}/mcp",
    )
    return {"Authorization": f"Bearer {token}"}


def _inventory() -> RemoteListMachinesOutput:
    return RemoteListMachinesOutput(
        machines=[
            RemoteMachineInfo(
                name="edge-a",
                status="online",
                workdir="/srv/edge-a",
                last_seen=100.0,
                last_seen_age_s=2.0,
                offline_after_s=60.0,
                queue_depth=3,
                capabilities=["shell", "files", "shell"],
                info={
                    "lsm_version": "3.9.1",
                    "hostname": "edge-host",
                    "user": "worker",
                    "python": "3.14.0",
                    "platform": "linux",
                    "cwd": "/srv/edge-a",
                    "workdir": "/srv/edge-a",
                    "worker_token": "must-not-leak",
                    "secret": "must-not-leak",
                },
            ),
            RemoteMachineInfo(
                name="edge-b",
                status="offline",
                workdir=None,
                last_seen=50.0,
                last_seen_age_s=52.0,
                offline_after_s=60.0,
                queue_depth=None,
                capabilities=[],
                info={},
            ),
        ],
        counts={"online": 999, "offline": 999, "total": 1998},
    )


def test_remotes_disabled_is_empty_and_mutations_conflict(
    monkeypatch, tmp_path
):
    client = _client(monkeypatch, tmp_path, remote_enabled=False)

    def fail_list():
        raise AssertionError("disabled inventory must not call the manager")

    monkeypatch.setattr(remotes_module, "list_remote_machines", fail_list)

    listed = client.get("/api/ui/remotes")
    invited = client.post("/api/ui/remotes", json={})
    renamed = client.post(
        "/api/ui/remotes/rename",
        json={"machine": "edge-a", "new_name": "edge-b"},
    )
    revoked = client.post(
        "/api/ui/remotes/revoke",
        json={"machine": "edge-a"},
    )

    assert listed.status_code == 200
    assert listed.json()["data"] == {
        "enabled": False,
        "machines": [],
        "counts": {"online": 0, "offline": 0, "total": 0},
        "invite_ttl_s": 600,
    }
    for response in (invited, renamed, revoked):
        assert response.status_code == 409
        assert response.json()["error"] == "RemoteWorkersDisabled"


def test_remotes_require_remote_use_scope(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path, auth_mode="oauth")
    monkeypatch.setattr(
        remotes_module,
        "list_remote_machines",
        lambda: RemoteListMachinesOutput(machines=[], counts={}),
    )

    assert client.get("/api/ui/remotes").status_code == 401
    assert (
        client.get(
            "/api/ui/remotes",
            headers=_headers(SCOPE_SHELL_READ),
        ).status_code
        == 403
    )
    allowed = client.get(
        "/api/ui/remotes",
        headers=_headers(SCOPE_REMOTE_USE),
    )
    assert allowed.status_code == 200
    assert allowed.json()["data"]["enabled"] is True


def test_remote_inventory_is_normalized_and_strips_private_info(
    monkeypatch, tmp_path
):
    client = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(remotes_module, "list_remote_machines", _inventory)

    response = client.get("/api/ui/remotes")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()["data"]
    assert payload["counts"] == {"online": 1, "offline": 1, "total": 2}
    assert payload["machines"][0] == {
        "name": "edge-a",
        "status": "online",
        "workdir": "/srv/edge-a",
        "last_seen": 100.0,
        "last_seen_age_s": 2.0,
        "offline_after_s": 60.0,
        "queue_depth": 3,
        "capabilities": ["shell", "files"],
        "info": {
            "lsm_version": "3.9.1",
            "hostname": "edge-host",
            "user": "worker",
            "python": "3.14.0",
            "platform": "linux",
            "cwd": "/srv/edge-a",
            "workdir": "/srv/edge-a",
        },
    }
    assert payload["machines"][1]["queue_depth"] == 0
    serialized = str(payload)
    assert "worker_token" not in serialized
    assert "must-not-leak" not in serialized


def test_remote_inventory_rejects_duplicate_and_malformed_rows(
    monkeypatch, tmp_path
):
    client = _client(monkeypatch, tmp_path)

    class DuplicateInventory:
        def model_dump(self, *, mode: str) -> dict[str, Any]:
            assert mode == "json"
            row = _inventory().machines[0].model_dump(mode="json")
            return {"machines": [row, row], "counts": {}}

    monkeypatch.setattr(
        remotes_module,
        "list_remote_machines",
        lambda: DuplicateInventory(),
    )
    duplicate = client.get("/api/ui/remotes")
    assert duplicate.status_code == 500
    assert duplicate.json() == {
        "ok": False,
        "error": "RemoteInventoryUnavailable",
        "message": "Remote worker inventory is unavailable",
    }

    class MalformedInventory:
        def model_dump(self, *, mode: str) -> dict[str, Any]:
            assert mode == "json"
            row = _inventory().machines[0].model_dump(mode="json")
            row["status"] = "revoked"
            return {"machines": [row], "counts": {}}

    monkeypatch.setattr(
        remotes_module,
        "list_remote_machines",
        lambda: MalformedInventory(),
    )
    malformed = client.get("/api/ui/remotes")
    assert malformed.status_code == 500
    assert malformed.json()["error"] == "RemoteInventoryUnavailable"


def test_remote_invite_is_bounded_ephemeral_and_audited_without_secret(
    monkeypatch, tmp_path
):
    client = _client(monkeypatch, tmp_path)
    calls: list[tuple[str | None, str | None, int | None]] = []
    audit_rows: list[tuple[str, dict[str, Any]]] = []

    async def fake_invite(
        name: str | None,
        workdir: str | None,
        ttl_s: int | None,
    ) -> RemoteInviteOutput:
        calls.append((name, workdir, ttl_s))
        return RemoteInviteOutput(
            code="one-time-code",
            name=name,
            workdir=workdir,
            expires_at=1_000.0,
            ttl_s=ttl_s or 600,
            join_url="https://secret.invalid/join?code=one-time-code",
            command="uvx local-shell-mcp remote-worker --invite one-time-code",
        )

    monkeypatch.setattr(remotes_module, "create_remote_invite", fake_invite)
    monkeypatch.setattr(
        remotes_module,
        "audit",
        lambda event, **fields: audit_rows.append((event, fields)),
    )

    response = client.post(
        "/api/ui/remotes",
        json={"name": " edge-a ", "workdir": " /srv/work ", "ttl_s": 600},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert calls == [("edge-a", "/srv/work", 600)]
    payload = response.json()["data"]
    assert payload == {
        "name": "edge-a",
        "workdir": "/srv/work",
        "expires_at": 1_000.0,
        "ttl_s": 600,
        "command": "uvx local-shell-mcp remote-worker --invite one-time-code",
    }
    assert "code" not in payload
    assert "join_url" not in payload
    assert audit_rows == [
        (
            "ui_remote_invite_created",
            {
                "machine": "edge-a",
                "workdir": "/srv/work",
                "expires_at": 1_000.0,
                "ttl_s": 600,
            },
        )
    ]
    assert "one-time-code" not in str(audit_rows)

    invalid = client.post(
        "/api/ui/remotes",
        json={"name": "bad/name", "ttl_s": 600},
    )
    assert invalid.status_code == 400
    extra = client.post(
        "/api/ui/remotes",
        json={"ttl_s": 600, "unexpected": True},
    )
    assert extra.status_code == 400


@pytest.mark.parametrize(
    ("message", "expected_status", "expected_error"),
    [
        (
            "Too many pending remote invites",
            429,
            "RemoteInviteCapacityExceeded",
        ),
        ("registry unavailable", 500, "RemoteInviteUnavailable"),
    ],
)
def test_remote_invite_errors_are_safe(
    monkeypatch,
    tmp_path,
    message,
    expected_status,
    expected_error,
):
    client = _client(monkeypatch, tmp_path)

    async def fail_invite(*args, **kwargs):
        raise RuntimeError(message)

    monkeypatch.setattr(remotes_module, "create_remote_invite", fail_invite)
    response = client.post("/api/ui/remotes", json={"ttl_s": 600})
    assert response.status_code == expected_status
    assert response.json()["error"] == expected_error
    assert "registry unavailable" not in response.text


def test_remote_rename_and_revoke_dispatch_and_audit(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    calls: list[tuple[str, ...]] = []
    audit_rows: list[tuple[str, dict[str, Any]]] = []

    def fake_rename(machine: str, new_name: str) -> RemoteRenameMachineOutput:
        calls.append(("rename", machine, new_name))
        return RemoteRenameMachineOutput(old_name=machine, new_name=new_name)

    def fake_revoke(machine: str) -> RemoteRevokeMachineOutput:
        calls.append(("revoke", machine))
        return RemoteRevokeMachineOutput(machine=machine, revoked=True)

    monkeypatch.setattr(remotes_module, "rename_remote_machine", fake_rename)
    monkeypatch.setattr(remotes_module, "revoke_remote_machine", fake_revoke)
    monkeypatch.setattr(
        remotes_module,
        "audit",
        lambda event, **fields: audit_rows.append((event, fields)),
    )

    renamed = client.post(
        "/api/ui/remotes/rename",
        json={"machine": "edge-a", "new_name": "edge-primary"},
    )
    revoked = client.post(
        "/api/ui/remotes/revoke",
        json={"machine": "edge-primary"},
    )

    assert renamed.status_code == 200
    assert renamed.json()["data"] == {
        "old_name": "edge-a",
        "new_name": "edge-primary",
    }
    assert revoked.status_code == 200
    assert revoked.json()["data"] == {
        "machine": "edge-primary",
        "revoked": True,
    }
    assert calls == [
        ("rename", "edge-a", "edge-primary"),
        ("revoke", "edge-primary"),
    ]
    assert audit_rows == [
        (
            "ui_remote_worker_renamed",
            {"machine": "edge-a", "new_name": "edge-primary"},
        ),
        ("ui_remote_worker_revoked", {"machine": "edge-primary"}),
    ]

    unsupported = client.post(
        "/api/ui/remotes/unknown",
        json={"machine": "edge-a"},
    )
    assert unsupported.status_code == 400
