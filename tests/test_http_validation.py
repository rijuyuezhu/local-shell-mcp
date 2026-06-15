from fastapi.testclient import TestClient

from local_shell_mcp.http_app import build_http_app
from local_shell_mcp.settings import get_settings


def test_http_missing_required_argument_returns_validation_error(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()

    response = TestClient(build_http_app()).post("/tools/read_file", json={})

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "error": "validation_error",
        "message": "Missing required argument: path",
    }


def test_http_exception_uses_consistent_error_envelope(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()

    response = TestClient(build_http_app()).post(
        "/tools/run_shell",
        json={"command": "echo ok", "timeout_s": 3600},
    )

    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert response.json()["error"] == "http_error"
    assert "timeout_s must be <= 120 seconds" in response.json()["message"]
