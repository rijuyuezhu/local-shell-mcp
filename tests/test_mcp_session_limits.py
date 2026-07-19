from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.server.mcp.app import build_mcp, build_mcp_http_app
from local_shell_mcp.server.mcp.session_limits import McpSessionLimitMiddleware


def _initialize_payload() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "session-limit-test", "version": "1"},
        },
    }


def _mcp_headers(**extra: str) -> dict[str, str]:
    return {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        **extra,
    }


@pytest.mark.asyncio
async def test_session_limit_prunes_terminated_bookkeeping_and_rejects_new_session():
    calls: list[Scope] = []
    messages: list[Message] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        calls.append(scope)

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        messages.append(message)

    manager = SimpleNamespace(
        stateless=False,
        _server_instances={
            "dead": SimpleNamespace(is_terminated=True),
            "live": SimpleNamespace(is_terminated=False),
        },
        _session_owners={"dead": "old", "live": "current"},
    )
    limiter = McpSessionLimitMiddleware(
        app,
        session_manager=manager,
        max_sessions=1,
    )

    assert limiter._active_session_count() == 1
    assert "dead" not in manager._server_instances
    assert "dead" not in manager._session_owners

    await limiter(
        {"type": "http", "path": "/mcp", "method": "POST", "headers": []},
        receive,
        send,
    )
    assert calls == []
    assert messages[0]["type"] == "http.response.start"
    assert messages[0]["status"] == 429

    await limiter(
        {
            "type": "http",
            "path": "/mcp",
            "method": "POST",
            "headers": [(b"mcp-session-id", b"live")],
        },
        receive,
        send,
    )
    assert len(calls) == 1


def test_stateful_mcp_sessions_have_idle_timeout_and_capacity_limit(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MCP_SESSION_IDLE_TIMEOUT_S", "7")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MCP_MAX_SESSIONS", "2")
    clear_settings_cache()

    mcp = build_mcp()
    app = build_mcp_http_app(mcp)
    manager = mcp._session_manager
    assert manager is not None
    assert manager.session_idle_timeout == 7

    with TestClient(app, base_url="http://127.0.0.1") as client:
        first = client.post(
            "/mcp", json=_initialize_payload(), headers=_mcp_headers()
        )
        second = client.post(
            "/mcp", json=_initialize_payload(), headers=_mcp_headers()
        )
        rejected = client.post(
            "/mcp", json=_initialize_payload(), headers=_mcp_headers()
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert rejected.status_code == 429
        assert rejected.json()["error"] == "mcp_session_limit"

        first_session = first.headers["mcp-session-id"]
        ping = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            headers=_mcp_headers(
                **{
                    "mcp-session-id": first_session,
                    "mcp-protocol-version": "2025-06-18",
                }
            ),
        )
        assert ping.status_code == 200

        deleted = client.delete(
            "/mcp",
            headers={
                "accept": "application/json",
                "mcp-session-id": first_session,
                "mcp-protocol-version": "2025-06-18",
            },
        )
        assert deleted.status_code == 200

        replacement = client.post(
            "/mcp", json=_initialize_payload(), headers=_mcp_headers()
        )
        assert replacement.status_code == 200
