import time

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from local_shell_mcp.downloads import create_share_link, download_routes, revoke_share_link
from local_shell_mcp.settings import get_settings
from local_shell_mcp.tools import build_mcp


def _reset(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://files.example.test")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET", "x" * 32)
    get_settings.cache_clear()


def test_create_share_link_serves_file(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")

    link = create_share_link("hello.txt", ttl_s=60, filename="result.txt", max_downloads=2)

    assert link["url"].startswith("https://files.example.test/download/")
    app = Starlette(routes=download_routes())
    response = TestClient(app).get(link["url"])

    assert response.status_code == 200
    assert response.text == "hello"
    assert "result.txt" in response.headers["content-disposition"]


def test_share_link_expires_and_can_be_revoked(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")

    link = create_share_link("hello.txt", ttl_s=1)
    token = link["token"]
    assert revoke_share_link(token)["revoked"] is True

    app = Starlette(routes=download_routes())
    assert TestClient(app).get(link["url"]).status_code == 404

    link = create_share_link("hello.txt", ttl_s=1)
    time.sleep(1.05)
    assert TestClient(app).get(link["url"]).status_code == 410


def test_share_link_download_limit(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    link = create_share_link("hello.txt", ttl_s=60, max_downloads=1)
    client = TestClient(Starlette(routes=download_routes()))

    assert client.get(link["url"]).status_code == 200
    assert client.get(link["url"]).status_code == 410


@pytest.mark.asyncio
async def test_file_link_tools_are_registered(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    names = {tool.name for tool in await build_mcp().list_tools()}

    assert {"create_file_link", "list_file_links", "revoke_file_link"} <= names
