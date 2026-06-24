import json
import time

import pytest
from fastapi.testclient import TestClient as FastAPITestClient
from starlette.applications import Starlette
from starlette.testclient import TestClient

from local_shell_mcp.config.settings import clear_settings_cache, get_settings
from local_shell_mcp.ops.downloads import (
    create_file_link_execute,
    download_token_fingerprint,
    list_file_links_execute,
    revoke_file_link_execute,
)
from local_shell_mcp.server.http.app import build_http_app
from local_shell_mcp.server.mcp.app import build_mcp
from local_shell_mcp.server.shared.downloads import (
    _token_fingerprint,
    download_routes,
)
from local_shell_mcp.tool_session.store import get_tool_session_store


def _reset(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_BASE_URL", "https://files.example.test")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()


def test_create_share_link_serves_file(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")

    link = create_file_link_execute(
        "hello.txt", ttl_s=60, filename="result.txt", max_downloads=2
    )

    assert link.url.startswith("https://files.example.test/download/")
    app = Starlette(routes=download_routes())
    response = TestClient(app).get(link.url)

    assert response.status_code == 200
    assert response.text == "hello"
    assert "result.txt" in response.headers["content-disposition"]


def test_share_link_expires_and_can_be_revoked(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")

    link = create_file_link_execute("hello.txt", ttl_s=1)
    token = link.token
    assert revoke_file_link_execute(token).revoked is True

    app = Starlette(routes=download_routes())
    assert TestClient(app).get(link.url).status_code == 404

    link = create_file_link_execute("hello.txt", ttl_s=1)
    time.sleep(1.05)
    assert TestClient(app).get(link.url).status_code == 410


def test_share_link_download_limit(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    link = create_file_link_execute("hello.txt", ttl_s=60, max_downloads=1)
    client = TestClient(Starlette(routes=download_routes()))

    assert client.get(link.url).status_code == 200
    assert client.get(link.url).status_code == 410


def test_share_link_can_be_disabled(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED", "false")
    clear_settings_cache()
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")

    with pytest.raises(PermissionError):
        create_file_link_execute("hello.txt", ttl_s=60)


def test_file_links_are_session_owned(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    store = get_tool_session_store()
    store.clear()
    first = store.create_session(workdir=".").session_id
    second = store.create_session(workdir=".").session_id

    link = create_file_link_execute("hello.txt", ttl_s=60, session_id=first)

    assert [
        item.token for item in list_file_links_execute(session_id=first).links
    ] == [link.token]
    assert list_file_links_execute(session_id=second).links == []
    assert (
        revoke_file_link_execute(link.token, session_id=second).revoked is False
    )
    assert (
        revoke_file_link_execute(link.token, session_id=first).revoked is True
    )


def test_file_links_reject_remote_sessions(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    store = get_tool_session_store()
    store.clear()
    remote = store.create_session(
        target="remote",
        workdir="/remote/project",
        machine="worker-a",
        worker_session_id="WORKER12",
    ).session_id

    with pytest.raises(ValueError, match="local sessions"):
        create_file_link_execute("hello.txt", ttl_s=60, session_id=remote)


@pytest.mark.asyncio
async def test_file_link_tools_are_registered(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODE", "mcp")
    clear_settings_cache()
    tools = {tool.name: tool for tool in await build_mcp().list_tools()}
    names = set(tools)

    assert {"create_file_link", "list_file_links", "revoke_file_link"} <= names

    create_tool = tools["create_file_link"]
    list_tool = tools["list_file_links"]
    assert create_tool.outputSchema is not None
    assert list_tool.outputSchema is not None
    assert create_tool.outputSchema["title"] == "CreateFileLinkOutput"
    assert list_tool.outputSchema["title"] == "ListFileLinksOutput"
    assert create_tool.inputSchema["properties"]["path"]["description"] == (
        "Existing regular file path to expose through a temporary tokenized download URL."
    )
    assert (
        create_tool.outputSchema["properties"]["url"]["description"]
        == "Browser-accessible download URL containing the token."
    )


@pytest.mark.asyncio
async def test_file_link_tools_are_hidden_in_stdio(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODE", "stdio")
    clear_settings_cache()
    names = {tool.name for tool in await build_mcp().list_tools()}

    assert {
        "create_file_link",
        "list_file_links",
        "revoke_file_link",
    }.isdisjoint(names)


def test_download_token_fingerprint_does_not_expose_token():
    token = "secret-download-token"

    fingerprint = _token_fingerprint(token)

    assert token not in fingerprint
    assert len(fingerprint) == 16
    assert fingerprint == _token_fingerprint(token)


def test_download_tokens_are_redacted_from_audit_logs(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    clear_settings_cache()
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")

    client = FastAPITestClient(build_http_app())
    session = client.post("/tools/session_start", json={"workdir": "."}).json()
    link = client.post(
        "/tools/file_link/create",
        json={"session_id": session["session_id"], "path": "hello.txt"},
    ).json()
    token = link["token"]
    assert token
    assert (
        client.post(
            "/tools/file_link/revoke",
            json={"session_id": session["session_id"], "token": token},
        ).status_code
        == 200
    )

    log_text = get_settings().audit_log_path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in log_text.splitlines() if line]

    assert token not in log_text
    assert link["url"] not in log_text
    assert "/download/<redacted>" in log_text
    assert download_token_fingerprint(token) in log_text
    assert any(
        record.get("event") == "download_link_created"
        and record.get("token_sha256") == download_token_fingerprint(token)
        for record in records
    )
    assert any(
        record.get("event") == "download_link_revoked"
        and record.get("token_sha256") == download_token_fingerprint(token)
        for record in records
    )
