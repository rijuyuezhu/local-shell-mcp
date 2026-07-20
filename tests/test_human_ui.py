import stat

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import local_shell_mcp.server.http.human_ui as human_ui_module
from local_shell_mcp.config.settings import Settings, clear_settings_cache
from local_shell_mcp.server.http.app import build_http_app
from local_shell_mcp.ui_security import (
    UI_LOCAL_TOKEN_HEADER,
    get_or_create_ui_local_token,
)


def _configure_ui(monkeypatch, tmp_path, *, auth_mode="none", **values):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", auth_mode)
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    for name, value in values.items():
        monkeypatch.setenv(
            f"LOCAL_SHELL_MCP_{name.upper()}", str(value).lower()
        )
    clear_settings_cache()


def test_ui_path_normalization_and_reserved_paths():
    assert Settings(ui_path="/console/").ui_path == "/console"
    assert Settings(ui_path="//human//ui//").ui_path == "/human/ui"

    for value in ("ui", "/", "/../ui", "/api", "/api/custom", "/ui?x=1"):
        with pytest.raises(ValidationError):
            Settings(ui_path=value)


def test_human_ui_shell_is_public_but_api_requires_oauth(monkeypatch, tmp_path):
    _configure_ui(monkeypatch, tmp_path, auth_mode="oauth")
    client = TestClient(build_http_app(), client=("203.0.113.10", 50000))

    index = client.get("/ui")
    assert index.status_code == 200
    assert "Human Interface" in index.text
    assert "__LSM_UI_PATH__" not in index.text
    assert index.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in index.headers["content-security-policy"]

    script = client.get("/ui/assets/web.js")
    assert script.status_code == 200
    assert script.headers["x-content-type-options"] == "nosniff"

    protected = client.get("/api/ui/bootstrap")
    assert protected.status_code == 401


def test_local_ui_token_bypasses_oauth_only_on_loopback(monkeypatch, tmp_path):
    _configure_ui(monkeypatch, tmp_path, auth_mode="oauth")
    token = get_or_create_ui_local_token()
    headers = {UI_LOCAL_TOKEN_HEADER: token}

    loopback = TestClient(build_http_app(), client=("127.0.0.1", 50000))
    response = loopback.get("/api/ui/bootstrap", headers=headers)
    assert response.status_code == 200
    assert response.json()["data"]["machines"][0]["name"] == "local"

    unrelated = loopback.get("/tools/list_persistent_shells", headers=headers)
    assert unrelated.status_code == 401

    external = TestClient(build_http_app(), client=("203.0.113.10", 50000))
    rejected = external.get("/api/ui/bootstrap", headers=headers)
    assert rejected.status_code == 401

    token_path = tmp_path / ".state" / "ui" / "local-token"
    assert token_path.read_text(encoding="utf-8").strip() == token
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600


def test_human_ui_custom_mount_and_bootstrap(monkeypatch, tmp_path):
    _configure_ui(monkeypatch, tmp_path, ui_path="/control")
    client = TestClient(build_http_app())

    assert client.get("/ui").status_code == 404
    index = client.get("/control")
    assert index.status_code == 200
    assert 'href="/control/assets/web.css"' in index.text

    payload = client.get("/api/ui/bootstrap").json()["data"]
    assert payload["ui"] == {
        "path": "/control",
        "api_prefix": "/api/ui",
        "auth_mode": "none",
        "features": {
            "dashboard": True,
            "machines": True,
            "terminals": False,
            "files": False,
            "todos": False,
            "audit": False,
        },
    }
    assert payload["counts"] == {"online": 1, "offline": 0, "total": 1}
    assert payload["machines"][0]["workdir"] == str(tmp_path)


def test_human_ui_can_be_disabled(monkeypatch, tmp_path):
    _configure_ui(monkeypatch, tmp_path, ui_enabled=False)
    client = TestClient(build_http_app())

    assert client.get("/ui").status_code == 404
    assert client.get("/api/ui/bootstrap").status_code == 404


def test_machine_inventory_includes_remote_rows(monkeypatch, tmp_path):
    _configure_ui(monkeypatch, tmp_path, remote_enabled=True)

    class FakeInventory:
        def model_dump(self, *, mode):
            assert mode == "json"
            return {
                "machines": [
                    {
                        "name": "worker-a",
                        "status": "offline",
                        "workdir": "/srv/work",
                        "last_seen": 0,
                        "last_seen_age_s": None,
                        "offline_after_s": 60,
                        "queue_depth": 0,
                        "capabilities": ["shell"],
                        "info": {"platform": "linux"},
                    }
                ],
                "counts": {"online": 0, "offline": 1, "total": 1},
            }

    class FakeManager:
        def list_machines(self):
            return FakeInventory()

    monkeypatch.setattr(human_ui_module, "remote_manager", FakeManager)
    payload = (
        TestClient(build_http_app()).get("/api/ui/machines").json()["data"]
    )

    assert [item["name"] for item in payload["machines"]] == [
        "local",
        "worker-a",
    ]
    assert payload["counts"] == {"online": 1, "offline": 1, "total": 2}
