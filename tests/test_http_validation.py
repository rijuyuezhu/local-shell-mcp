from fastapi.testclient import TestClient

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.server.http.app import build_http_app


def test_http_missing_required_argument_returns_validation_error(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    response = TestClient(build_http_app()).post("/tools/read", json={})

    assert response.status_code == 400
    assert response.json() == {
        "error": "validation_error",
        "message": "Missing required argument: session_id",
    }


def test_http_exception_uses_consistent_error_envelope(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    clear_settings_cache()

    response = TestClient(build_http_app()).post(
        "/tools/bash",
        json={"command": "echo ok", "timeout_s": 3600},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "validation_error"
    assert "timeout_s must be <= 60 seconds" in response.json()["message"]
