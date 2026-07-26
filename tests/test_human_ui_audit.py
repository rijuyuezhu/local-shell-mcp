from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import local_shell_mcp.ui.http.audit as ui_audit_module
import local_shell_mcp.ui.http.common as ui_common_module
from local_shell_mcp.audit import audit
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.executors.http.app import build_http_app
from local_shell_mcp.oauth.core.scopes import (
    SCOPE_AUDIT_FULL,
    SCOPE_AUDIT_READ,
    SCOPE_REMOTE_USE,
    SCOPE_SHELL_EXECUTE,
    SCOPE_SHELL_WRITE,
)
from local_shell_mcp.oauth.protocol.token_codec import issue_access_token
from local_shell_mcp.remote_worker.dispatch import execute_worker_tool
from local_shell_mcp.schemas.result_models.remote import (
    RemoteListMachinesOutput,
    RemoteMachineInfo,
)
from local_shell_mcp.tool_session.store import get_tool_session_store

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
    remote_enabled: bool = False,
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
    clear_settings_cache()


def _client(
    monkeypatch,
    tmp_path: Path,
    *,
    auth_mode: str = "none",
    remote_enabled: bool = False,
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
        client=("203.0.113.14", 50005),
    )


def _token(scope: str) -> str:
    return issue_access_token(
        client_id="webui-audit-test",
        scope=scope,
        resource=f"{BASE_URL}/mcp",
    )


def _headers(scope: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(scope)}"}


def test_local_audit_lists_filters_and_returns_details(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    audit(
        "tool_call_start",
        call_id="local-read",
        tool="read",
        transport="http",
        session_id="session-local",
        input={"path": "alpha.txt"},
    )
    audit(
        "tool_call_end",
        call_id="local-read",
        tool="read",
        transport="http",
        ok=True,
        duration_ms=4,
        output={"content": "alpha"},
    )
    audit("job_started", job_id="job-1", command="compile beta")

    response = client.get(
        "/api/ui/audit",
        params={
            "machine": "local",
            "operation": "files",
            "session": "session-local",
            "search": "READ",
            "sort": "asc",
            "limit": 100,
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["machine"] == "local"
    assert payload["remote"] is False
    assert payload["count"] == 1
    assert payload["total_matched"] == 1
    summary = payload["entries"][0]
    assert summary["id"] == "call:local-read"
    assert summary["node"] == "local"
    assert "input" not in summary
    assert "output" not in summary
    assert "error" not in summary

    detail = client.get(
        "/api/ui/audit/detail",
        params={"machine": "local", "id": "call:local-read"},
    )
    assert detail.status_code == 200
    entry = detail.json()["data"]["entry"]
    assert entry["input"] == {"path": "alpha.txt"}
    assert entry["output"] == {"content": "alpha"}
    assert entry["status"] == "success"


def test_audit_detail_enforces_operation_sensitive_scopes(
    monkeypatch, tmp_path
):
    client = _client(monkeypatch, tmp_path, auth_mode="oauth")
    audit(
        "tool_call_start",
        call_id="local-write",
        tool="write_file",
        transport="http",
        input={"path": "notes.txt", "content": "hello"},
    )
    audit(
        "tool_call_end",
        call_id="local-write",
        tool="write_file",
        transport="http",
        ok=True,
        duration_ms=3,
        output={"path": "notes.txt"},
    )

    read_only = _headers(SCOPE_AUDIT_READ)
    read_write = _headers(f"{SCOPE_AUDIT_READ} {SCOPE_SHELL_WRITE}")

    listing = client.get("/api/ui/audit", headers=read_only)
    denied = client.get(
        "/api/ui/audit/detail",
        params={"id": "call:local-write"},
        headers=read_only,
    )
    allowed = client.get(
        "/api/ui/audit/detail",
        params={"id": "call:local-write"},
        headers=read_write,
    )

    assert listing.status_code == 200
    assert denied.status_code == 403
    assert SCOPE_SHELL_WRITE in denied.text
    assert allowed.status_code == 200


def test_audit_detail_full_payloads_require_audit_full(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path, auth_mode="oauth")
    audit(
        "job_started",
        job_id="large-job",
        command="x" * 20_000,
    )
    entry_id = client.get(
        "/api/ui/audit",
        headers=_headers(SCOPE_AUDIT_READ),
    ).json()["data"]["entries"][0]["id"]

    denied = client.get(
        "/api/ui/audit/detail",
        params={"id": entry_id, "include_full_payloads": "true"},
        headers=_headers(f"{SCOPE_AUDIT_READ} {SCOPE_SHELL_EXECUTE}"),
    )
    allowed = client.get(
        "/api/ui/audit/detail",
        params={"id": entry_id, "include_full_payloads": "true"},
        headers=_headers(
            f"{SCOPE_AUDIT_READ} {SCOPE_AUDIT_FULL} {SCOPE_SHELL_EXECUTE}"
        ),
    )

    assert denied.status_code == 403
    assert SCOPE_AUDIT_FULL in denied.text
    assert allowed.status_code == 200
    command = allowed.json()["data"]["entry"]["command"]
    assert command == "x" * 20_000


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
                    capabilities=["audit"],
                    info={},
                )
            ],
            counts={self.status: 1, "total": 1},
        )


class _FakeRemoteAudit:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], int]] = []
        self.malformed = False
        self.worker_session_id = ""

    async def call(
        self,
        machine: str,
        tool: str,
        args: dict[str, Any],
        timeout_s: int,
    ) -> dict[str, Any]:
        assert machine == "edge"
        assert 1 <= timeout_s <= 60
        assert "session_id" not in args
        self.calls.append((tool, dict(args), timeout_s))
        if self.malformed:
            return {"ok": True, "data": {"entries": "bad"}}
        entry = {
            "id": "call:remote-shell",
            "ts": 2.0,
            "event": "tool_call",
            "tool": "bash",
            "operation": "shell",
            "status": "success",
            "paired": True,
            "input": {"command": "printf safe"},
            "output": {"stdout": "safe"},
        }
        if self.worker_session_id:
            entry["session"] = self.worker_session_id
        if tool == "query_audit":
            return {
                "ok": True,
                "data": {
                    "entries": [entry],
                    "count": 1,
                    "total_matched": 1,
                },
            }
        assert tool == "get_audit_entry"
        assert args == {
            "id": "call:remote-shell",
            "include_full_payloads": False,
        }
        return {"ok": True, "data": entry}


def _remote_client(
    monkeypatch,
    tmp_path: Path,
    fake: _FakeRemoteAudit,
    *,
    auth_mode: str = "none",
    status: str = "online",
) -> TestClient:
    client = _client(
        monkeypatch,
        tmp_path,
        auth_mode=auth_mode,
        remote_enabled=True,
    )
    monkeypatch.setattr(
        ui_common_module,
        "remote_manager",
        lambda: _FakeManager(status=status),
    )
    monkeypatch.setattr(ui_audit_module, "call_remote_worker_tool", fake.call)
    return client


def test_remote_audit_uses_process_scoped_native_worker_rpc(
    monkeypatch, tmp_path
):
    fake = _FakeRemoteAudit()
    client = _remote_client(monkeypatch, tmp_path, fake)

    listing = client.get(
        "/api/ui/audit",
        params={"machine": "edge", "operation": "shell", "limit": 100},
    )
    detail = client.get(
        "/api/ui/audit/detail",
        params={"machine": "edge", "id": "call:remote-shell"},
    )

    assert listing.status_code == 200
    remote_summary = listing.json()["data"]["entries"][0]
    assert remote_summary["node"] == "edge"
    assert "input" not in remote_summary
    assert "output" not in remote_summary
    assert listing.json()["data"]["remote"] is True
    assert detail.status_code == 200
    assert detail.json()["data"]["entry"]["node"] == "edge"
    assert [call[0] for call in fake.calls] == [
        "query_audit",
        "get_audit_entry",
    ]
    assert fake.calls[0][1]["operation"] == "shell"


def test_remote_audit_maps_public_session_filters_to_worker_ids(
    monkeypatch, tmp_path
):
    fake = _FakeRemoteAudit()
    fake.worker_session_id = "worker01"
    client = _remote_client(monkeypatch, tmp_path, fake)
    session = get_tool_session_store().create_session(
        target="remote",
        machine="edge",
        workdir="/srv/project",
        worker_session_id=fake.worker_session_id,
        label="remote audit",
    )

    listing = client.get(
        "/api/ui/audit",
        params={"machine": "edge", "session": session.session_id},
    )

    assert listing.status_code == 200
    assert fake.calls[0][1]["session"] == fake.worker_session_id
    assert listing.json()["data"]["entries"][0]["session"] == session.session_id


def test_remote_audit_scopes_offline_and_malformed_returns(
    monkeypatch, tmp_path
):
    fake = _FakeRemoteAudit()
    client = _remote_client(
        monkeypatch,
        tmp_path,
        fake,
        auth_mode="oauth",
    )
    read_only = _headers(SCOPE_AUDIT_READ)
    remote_read = _headers(f"{SCOPE_AUDIT_READ} {SCOPE_REMOTE_USE}")
    remote_execute = _headers(
        f"{SCOPE_AUDIT_READ} {SCOPE_SHELL_EXECUTE} {SCOPE_REMOTE_USE}"
    )

    missing_remote = client.get(
        "/api/ui/audit",
        params={"machine": "edge"},
        headers=read_only,
    )
    readable = client.get(
        "/api/ui/audit",
        params={"machine": "edge"},
        headers=remote_read,
    )
    missing_execute = client.get(
        "/api/ui/audit/detail",
        params={"machine": "edge", "id": "call:remote-shell"},
        headers=remote_read,
    )
    executable = client.get(
        "/api/ui/audit/detail",
        params={"machine": "edge", "id": "call:remote-shell"},
        headers=remote_execute,
    )

    assert missing_remote.status_code == 403
    assert SCOPE_REMOTE_USE in missing_remote.text
    assert readable.status_code == 200
    assert missing_execute.status_code == 403
    assert SCOPE_SHELL_EXECUTE in missing_execute.text
    assert executable.status_code == 200

    fake.malformed = True
    malformed = client.get(
        "/api/ui/audit",
        params={"machine": "edge"},
        headers=remote_read,
    )
    assert malformed.status_code == 502
    assert "malformed audit entries" in malformed.text

    offline_fake = _FakeRemoteAudit()
    offline_client = _remote_client(
        monkeypatch,
        tmp_path / "offline",
        offline_fake,
        status="offline",
    )
    offline = offline_client.get("/api/ui/audit", params={"machine": "edge"})
    assert offline.status_code == 503
    assert "offline" in offline.text
    assert offline_fake.calls == []


@pytest.mark.asyncio
async def test_remote_worker_dispatch_exposes_process_scoped_audit(
    monkeypatch, tmp_path
):
    _configure(monkeypatch, tmp_path / "worker")
    audit(
        "tool_call_start",
        call_id="worker-read",
        tool="read",
        transport="worker",
        input={"path": "remote.txt"},
    )
    audit(
        "tool_call_end",
        call_id="worker-read",
        tool="read",
        transport="worker",
        ok=True,
        duration_ms=1,
        output={"content": "remote"},
    )

    listing = await execute_worker_tool(
        "query_audit", {"operation": "files", "limit": 10}
    )
    detail = await execute_worker_tool(
        "get_audit_entry", {"id": "call:worker-read"}
    )

    assert listing["count"] == 1
    assert listing["entries"][0]["id"] == "call:worker-read"
    assert detail["output"] == {"content": "remote"}


def test_audit_api_validates_bounds_and_unknown_details(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    assert client.get("/api/ui/audit", params={"limit": 0}).status_code == 400
    assert (
        client.get("/api/ui/audit", params={"sort": "sideways"}).status_code
        == 400
    )
    assert (
        client.get(
            "/api/ui/audit", params={"start_ts": 2, "end_ts": 1}
        ).status_code
        == 400
    )
    missing = client.get("/api/ui/audit/detail", params={"id": "missing"})
    assert missing.status_code == 404


def test_audit_detail_sanitizes_and_previews_view_image(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg=="
    )
    audit(
        "tool_call_start",
        call_id="local-image",
        tool="view_image",
        transport="http",
        input={"path": "pixel.png"},
    )
    audit(
        "tool_call_end",
        call_id="local-image",
        tool="view_image",
        transport="http",
        ok=True,
        output={
            "content": [
                {
                    "type": "image",
                    "data": base64.b64encode(png).decode("ascii"),
                    "mimeType": "image/png",
                }
            ],
            "structuredContent": {"path": "pixel.png"},
        },
    )

    response = client.get(
        "/api/ui/audit/detail",
        params={
            "id": "call:local-image",
            "columns": 10,
            "rows": 5,
            "cell_aspect": 2,
        },
    )

    assert response.status_code == 200
    entry = response.json()["data"]["entry"]
    assert "data" not in entry["output"]["content"][0]
    assert entry["output"]["content"][0]["bytes"] == len(png)
    preview = entry["image_preview"]
    assert preview["kind"] == "image"
    assert preview["path"] == "pixel.png"
    assert preview["bytes"] == len(png)
    assert preview["mime_type"] == "image/png"
    assert preview["data_base64"] == base64.b64encode(png).decode("ascii")
    assert len(base64.b64decode(preview["rgba"])) == (
        preview["width"] * preview["height"] * 4
    )


def test_audit_detail_rejects_invalid_inline_image(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    audit(
        "tool_call_start",
        call_id="invalid-image",
        tool="view_image",
        transport="http",
    )
    audit(
        "tool_call_end",
        call_id="invalid-image",
        tool="view_image",
        transport="http",
        ok=False,
        output={"content": [{"type": "image", "data": "not-base64"}]},
    )

    response = client.get(
        "/api/ui/audit/detail", params={"id": "call:invalid-image"}
    )

    assert response.status_code == 200
    entry = response.json()["data"]["entry"]
    assert "data" not in entry["output"]["content"][0]
    assert "image_preview" not in entry
    assert entry["image_preview_error"]


def test_audit_static_ui_has_machine_guards_and_safe_detail_rendering():
    static_root = (
        Path(__file__).parents[1] / "src" / "local_shell_mcp" / "ui" / "static"
    )
    index = (static_root / "index.html").read_text(encoding="utf-8")
    script = (static_root / "web.js").read_text(encoding="utf-8")

    assert 'id="audit-machine"' in index
    assert 'id="audit-list"' in index
    assert 'id="audit-detail-body"' in index
    assert "auditGeneration" in script
    assert "auditDetailGeneration" in script
    assert "URLSearchParams" in script
    assert "renderAuditDetail(entry)" in script
    assert "elements.auditDetailBody.innerHTML" not in script
    assert "audit-image-preview" in script
    assert (
        "session_id"
        not in script[
            script.index("function auditQueryPath") : script.index(
                "function terminalSocketProtocols"
            )
        ]
    )
