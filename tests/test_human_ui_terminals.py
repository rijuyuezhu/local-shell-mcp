import base64
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

import local_shell_mcp.server.http.ui_terminals as terminal_module
from local_shell_mcp.config.settings import Settings, clear_settings_cache
from local_shell_mcp.oauth.core.scopes import (
    SCOPE_REMOTE_USE,
    SCOPE_SHELL_EXECUTE,
    SCOPE_SHELL_READ,
)
from local_shell_mcp.oauth.protocol.token_codec import issue_access_token
from local_shell_mcp.schemas.result_models.shell import (
    KillPersistentShellOutput,
    ListPersistentShellsOutput,
    PersistentShellInfo,
    ReadPersistentShellOutput,
    ResizePersistentShellOutput,
    SendPersistentShellInputOutput,
    StartPersistentShellOutput,
)
from local_shell_mcp.server.http.app import build_http_app

BASE_URL = "https://local-shell-mcp.example"


def test_terminal_settings_are_bounded():
    assert Settings().ui_terminal_idle_timeout_s == 3600
    assert Settings().ui_terminal_max_connections == 8
    with pytest.raises(ValidationError):
        Settings(ui_terminal_idle_timeout_s=-1)
    for value in (0, 129):
        with pytest.raises(ValidationError):
            Settings(ui_terminal_max_connections=value)


@pytest.fixture(autouse=True)
def _reset_settings_and_connections():
    clear_settings_cache()
    terminal_module._ACTIVE_CONNECTIONS.clear()
    yield
    terminal_module._ACTIVE_CONNECTIONS.clear()
    clear_settings_cache()


def _configure(monkeypatch, tmp_path, *, auth_mode="none", **values):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", auth_mode)
    monkeypatch.setenv("LOCAL_SHELL_MCP_BASE_URL", BASE_URL)
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    for name, value in values.items():
        monkeypatch.setenv(
            f"LOCAL_SHELL_MCP_{name.upper()}", str(value).lower()
        )
    clear_settings_cache()


def _client(monkeypatch, tmp_path, *, auth_mode="none", **values) -> TestClient:
    _configure(monkeypatch, tmp_path, auth_mode=auth_mode, **values)
    return TestClient(
        build_http_app(),
        base_url=BASE_URL,
        client=("203.0.113.10", 50000),
    )


def test_terminal_connection_limit(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, ui_terminal_max_connections=1)
    marker = terminal_module._reserve_connection()
    assert marker is not None
    assert terminal_module._reserve_connection() is None
    terminal_module._release_connection(marker)
    replacement = terminal_module._reserve_connection()
    assert replacement is not None
    terminal_module._release_connection(replacement)


def _bearer_token(scope: str) -> str:
    return issue_access_token(
        client_id="webui-test",
        scope=scope,
        resource=f"{BASE_URL}/mcp",
    )


def _bearer_protocol(scope: str) -> str:
    encoded = (
        base64.urlsafe_b64encode(_bearer_token(scope).encode())
        .rstrip(b"=")
        .decode()
    )
    return f"bearer.{encoded}"


def test_terminal_http_surface_dispatches_bounded_actions(
    monkeypatch, tmp_path
):
    calls: list[tuple] = []

    async def fake_list():
        return ListPersistentShellsOutput(
            shells=[PersistentShellInfo(shell_id="demo")]
        )

    async def fake_start(cwd=".", name=None, command=None):
        calls.append(("start", cwd, name, command))
        return StartPersistentShellOutput(
            shell_id="created", cwd=cwd, command=command or "/bin/sh"
        )

    async def fake_send(shell_id, input_text, enter=True):
        calls.append(("send", shell_id, input_text, enter))
        return SendPersistentShellInputOutput(
            shell_id=shell_id,
            sent_bytes=len(input_text.encode()),
            enter=enter,
        )

    async def fake_resize(shell_id, cols, rows):
        calls.append(("resize", shell_id, cols, rows))
        return ResizePersistentShellOutput(
            shell_id=shell_id,
            cols=cols,
            rows=rows,
            resized=True,
            backend="tmux",
        )

    async def fake_read(shell_id, lines=200, *, preserve_ansi=False):
        calls.append(("read", shell_id, lines, preserve_ansi))
        return ReadPersistentShellOutput(shell_id=shell_id, output="hello")

    async def fake_kill(shell_id):
        calls.append(("kill", shell_id))
        return KillPersistentShellOutput(shell_id=shell_id, killed=True)

    monkeypatch.setattr(
        terminal_module, "list_persistent_shells_execute", fake_list
    )
    monkeypatch.setattr(
        terminal_module, "start_persistent_shell_execute", fake_start
    )
    monkeypatch.setattr(
        terminal_module, "send_persistent_shell_input_execute", fake_send
    )
    monkeypatch.setattr(
        terminal_module, "resize_persistent_shell_execute", fake_resize
    )
    monkeypatch.setattr(
        terminal_module, "read_persistent_shell_output_execute", fake_read
    )
    monkeypatch.setattr(
        terminal_module, "kill_persistent_shell_execute", fake_kill
    )
    client = _client(monkeypatch, tmp_path)

    listed = client.get("/api/ui/terminals")
    assert listed.status_code == 200
    assert listed.json()["data"]["shells"][0]["shell_id"] == "demo"

    started = client.post(
        "/api/ui/terminals/start",
        json={"cwd": ".", "name": "created", "command": "/bin/sh"},
    )
    assert started.status_code == 200
    assert started.json()["data"]["shell_id"] == "created"

    sent = client.post(
        "/api/ui/terminals/send",
        json={"shell_id": "demo", "input_text": "printf ok", "enter": False},
    )
    assert sent.status_code == 200

    resized = client.post(
        "/api/ui/terminals/resize",
        json={"shell_id": "demo", "cols": 132, "rows": 41},
    )
    assert resized.status_code == 200

    read = client.get(
        "/api/ui/terminals/read", params={"shell_id": "demo", "lines": 321}
    )
    assert read.status_code == 200
    assert read.json()["data"]["output"] == "hello"

    killed = client.post("/api/ui/terminals/kill", json={"shell_id": "demo"})
    assert killed.status_code == 200
    assert calls == [
        ("start", ".", "created", "/bin/sh"),
        ("send", "demo", "printf ok", False),
        ("resize", "demo", 132, 41),
        ("read", "demo", 321, True),
        ("kill", "demo"),
    ]


def test_terminal_http_actions_require_execute_scope(monkeypatch, tmp_path):
    async def fake_list():
        return ListPersistentShellsOutput(
            shells=[PersistentShellInfo(shell_id="demo")]
        )

    async def fake_start(cwd=".", name=None, command=None):
        return StartPersistentShellOutput(shell_id="created", cwd=cwd)

    monkeypatch.setattr(
        terminal_module, "list_persistent_shells_execute", fake_list
    )
    monkeypatch.setattr(
        terminal_module, "start_persistent_shell_execute", fake_start
    )
    client = _client(monkeypatch, tmp_path, auth_mode="oauth")
    read_headers = {
        "Authorization": f"Bearer {_bearer_token(SCOPE_SHELL_READ)}"
    }
    execute_headers = {
        "Authorization": (
            "Bearer "
            + _bearer_token(f"{SCOPE_SHELL_READ} {SCOPE_SHELL_EXECUTE}")
        )
    }

    assert (
        client.get("/api/ui/terminals", headers=read_headers).status_code == 200
    )
    denied = client.post(
        "/api/ui/terminals/start", json={"cwd": "."}, headers=read_headers
    )
    assert denied.status_code == 403
    assert SCOPE_SHELL_EXECUTE in denied.text
    allowed = client.post(
        "/api/ui/terminals/start", json={"cwd": "."}, headers=execute_headers
    )
    assert allowed.status_code == 200


@pytest.mark.parametrize(
    ("path", "payload", "message"),
    [
        (
            "/api/ui/terminals/read?shell_id=bad%2Fid",
            None,
            "shell_id must be",
        ),
        (
            "/api/ui/terminals/read?shell_id=demo&lines=5001",
            None,
            "lines must be between",
        ),
        (
            "/api/ui/terminals/send",
            {
                "shell_id": "demo",
                "input_text": "x"
                * (terminal_module.UI_TERMINAL_INPUT_MAX_BYTES + 1),
            },
            "input_text exceeds",
        ),
        (
            "/api/ui/terminals/resize",
            {"shell_id": "demo", "cols": 19, "rows": 30},
            "cols must be between",
        ),
    ],
)
def test_terminal_http_surface_rejects_invalid_bounds(
    monkeypatch, tmp_path, path, payload, message
):
    client = _client(monkeypatch, tmp_path)
    response = (
        client.get(path) if payload is None else client.post(path, json=payload)
    )
    assert response.status_code == 400
    assert message in response.json()["message"]


def test_terminal_websocket_requires_oauth_and_execute_scope(
    monkeypatch, tmp_path
):
    async def fake_list():
        return ListPersistentShellsOutput(
            shells=[PersistentShellInfo(shell_id="demo")]
        )

    monkeypatch.setattr(
        terminal_module, "list_persistent_shells_execute", fake_list
    )
    client = _client(monkeypatch, tmp_path, auth_mode="oauth")

    with (
        pytest.raises(WebSocketDisconnect) as missing,
        client.websocket_connect(
            "/ui/ws/terminals/demo", subprotocols=["lsm-ui-terminal"]
        ),
    ):
        pass
    assert missing.value.code == 4401

    read_only = _bearer_protocol(SCOPE_SHELL_READ)
    with (
        pytest.raises(WebSocketDisconnect) as insufficient,
        client.websocket_connect(
            "/ui/ws/terminals/demo",
            subprotocols=["lsm-ui-terminal", read_only],
        ),
    ):
        pass
    assert insufficient.value.code == 4403


def test_terminal_websocket_reports_shell_inventory_failure(
    monkeypatch, tmp_path
):
    async def fake_list():
        raise RuntimeError("tmux unavailable")

    monkeypatch.setattr(
        terminal_module, "list_persistent_shells_execute", fake_list
    )
    client = _client(monkeypatch, tmp_path)
    with (
        pytest.raises(WebSocketDisconnect) as failure,
        client.websocket_connect(
            "/ui/ws/terminals/demo", subprotocols=["lsm-ui-terminal"]
        ),
    ):
        pass
    assert failure.value.code == 1011
    assert failure.value.reason == "Unable to inspect persistent shells"


def test_terminal_websocket_streams_snapshot_and_orders_controls(
    monkeypatch, tmp_path
):
    calls: list[tuple] = []
    input_seen = threading.Event()

    async def fake_list():
        return ListPersistentShellsOutput(
            shells=[PersistentShellInfo(shell_id="demo")]
        )

    async def fake_read(shell_id, lines=200, *, preserve_ansi=False):
        assert preserve_ansi is True
        return ReadPersistentShellOutput(
            shell_id=shell_id, output="\x1b[32mprompt$ \x1b[0m"
        )

    async def fake_send(shell_id, input_text, enter=True):
        calls.append(("send", shell_id, input_text, enter))
        input_seen.set()
        return SendPersistentShellInputOutput(
            shell_id=shell_id,
            sent_bytes=len(input_text.encode()),
            enter=enter,
        )

    async def fake_resize(shell_id, cols, rows):
        calls.append(("resize", shell_id, cols, rows))
        return ResizePersistentShellOutput(
            shell_id=shell_id,
            cols=cols,
            rows=rows,
            resized=True,
            backend="tmux",
        )

    monkeypatch.setattr(
        terminal_module, "list_persistent_shells_execute", fake_list
    )
    monkeypatch.setattr(
        terminal_module, "read_persistent_shell_output_execute", fake_read
    )
    monkeypatch.setattr(
        terminal_module, "send_persistent_shell_input_execute", fake_send
    )
    monkeypatch.setattr(
        terminal_module, "resize_persistent_shell_execute", fake_resize
    )
    client = _client(monkeypatch, tmp_path, auth_mode="oauth")
    bearer = _bearer_protocol(f"{SCOPE_SHELL_READ} {SCOPE_SHELL_EXECUTE}")

    with client.websocket_connect(
        "/ui/ws/terminals/demo?lines=1000",
        subprotocols=["lsm-ui-terminal", bearer],
    ) as websocket:
        assert websocket.accepted_subprotocol == "lsm-ui-terminal"
        assert websocket.receive_json() == {
            "type": "snapshot",
            "machine": "local",
            "shell_id": "demo",
            "output": "\x1b[32mprompt$ \x1b[0m",
        }
        websocket.send_json(
            {"type": "input", "data": "printf ok", "enter": True}
        )
        websocket.send_json({"type": "resize", "cols": 120, "rows": 36})
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {
            "type": "pong",
            "machine": "local",
            "shell_id": "demo",
        }
        assert input_seen.wait(timeout=1)
        websocket.send_json({"type": "close"})

    assert calls == [
        ("send", "demo", "printf ok", True),
        ("resize", "demo", 120, 36),
    ]
    assert not terminal_module._ACTIVE_CONNECTIONS


class _RemoteTerminalManager:
    def __init__(self, status: str = "online") -> None:
        self.status = status

    def list_machines(self):
        return SimpleNamespace(
            machines=[SimpleNamespace(name="edge", status=self.status)]
        )


class _RemoteTerminalCalls:
    def __init__(self, *, malformed: str = "") -> None:
        self.calls: list[tuple[str, str, dict, int]] = []
        self.malformed = malformed

    async def __call__(self, machine, tool, args, timeout_s):
        self.calls.append((machine, tool, args, timeout_s))
        if self.malformed == tool:
            data = (
                {"shells": [{"shell_id": "bad id"}]}
                if tool == "list_persistent_shells"
                else {"shell_id": "wrong"}
            )
            return {"ok": True, "data": data}
        outputs = {
            "list_persistent_shells": {
                "shells": [
                    {"shell_id": "shared", "name": "edge-shell", "cwd": "/edge"}
                ]
            },
            "start_persistent_shell": {
                "shell_id": "created",
                "name": args.get("name"),
                "cwd": args.get("cwd", "."),
                "command": args.get("command") or "/bin/sh",
            },
            "send_persistent_shell_input": {
                "shell_id": args.get("shell_id"),
                "sent_bytes": len(str(args.get("input_text") or "").encode()),
                "enter": bool(args.get("enter", True)),
            },
            "resize_persistent_shell": {
                "shell_id": args.get("shell_id"),
                "cols": args.get("cols"),
                "rows": args.get("rows"),
                "resized": True,
                "backend": "tmux",
            },
            "read_persistent_shell_output": {
                "shell_id": args.get("shell_id"),
                "output": "\x1b[36medge$ \x1b[0m",
            },
            "kill_persistent_shell": {
                "shell_id": args.get("shell_id"),
                "killed": True,
                "stderr": None,
            },
        }
        return {"ok": True, "data": outputs[tool]}


def _remote_terminal_client(
    monkeypatch,
    tmp_path,
    calls: _RemoteTerminalCalls,
    *,
    auth_mode: str = "none",
    status: str = "online",
):
    client = _client(
        monkeypatch,
        tmp_path,
        auth_mode=auth_mode,
        remote_enabled=True,
    )
    monkeypatch.setattr(
        terminal_module,
        "remote_manager",
        lambda: _RemoteTerminalManager(status),
    )
    monkeypatch.setattr(terminal_module, "call_remote_worker_tool", calls)
    return client


def test_remote_terminal_http_is_machine_scoped_and_sessionless(
    monkeypatch, tmp_path
):
    calls = _RemoteTerminalCalls()
    client = _remote_terminal_client(monkeypatch, tmp_path, calls)

    listed = client.get("/api/ui/terminals", params={"machine": "edge"})
    started = client.post(
        "/api/ui/terminals/start",
        json={"machine": "edge", "cwd": ".", "name": "created"},
    )
    sent = client.post(
        "/api/ui/terminals/send",
        json={
            "machine": "edge",
            "shell_id": "shared",
            "input_text": "printf ok",
            "enter": False,
        },
    )
    resized = client.post(
        "/api/ui/terminals/resize",
        json={"machine": "edge", "shell_id": "shared", "cols": 120, "rows": 36},
    )
    read = client.get(
        "/api/ui/terminals/read",
        params={"machine": "edge", "shell_id": "shared", "lines": 50},
    )
    killed = client.post(
        "/api/ui/terminals/kill",
        json={"machine": "edge", "shell_id": "shared"},
    )

    assert [
        response.status_code
        for response in (listed, started, sent, resized, read, killed)
    ] == [200] * 6
    assert listed.json()["data"] == {
        "machine": "edge",
        "remote": True,
        "shells": [
            {
                "shell_id": "shared",
                "name": "edge-shell",
                "cwd": "/edge",
                "command": None,
            }
        ],
    }
    assert started.json()["data"]["machine"] == "edge"
    assert read.json()["data"]["output"] == "\x1b[36medge$ \x1b[0m"
    assert all(
        machine == "edge" and 1 <= timeout <= 60
        for machine, _, _, timeout in calls.calls
    )
    assert all("session_id" not in args for _, _, args, _ in calls.calls)
    assert [tool for _, tool, _, _ in calls.calls] == [
        "list_persistent_shells",
        "start_persistent_shell",
        "send_persistent_shell_input",
        "resize_persistent_shell",
        "read_persistent_shell_output",
        "kill_persistent_shell",
    ]
    assert calls.calls[4][2] == {
        "shell_id": "shared",
        "lines": 50,
        "preserve_ansi": True,
    }


def test_remote_terminal_requires_scope_and_handles_offline_and_malformed(
    monkeypatch, tmp_path
):
    calls = _RemoteTerminalCalls()
    client = _remote_terminal_client(
        monkeypatch, tmp_path, calls, auth_mode="oauth"
    )
    denied = client.get(
        "/api/ui/terminals",
        params={"machine": "edge"},
        headers={"Authorization": f"Bearer {_bearer_token(SCOPE_SHELL_READ)}"},
    )
    allowed_scope = f"{SCOPE_SHELL_READ} {SCOPE_REMOTE_USE}"
    allowed = client.get(
        "/api/ui/terminals",
        params={"machine": "edge"},
        headers={"Authorization": f"Bearer {_bearer_token(allowed_scope)}"},
    )
    assert denied.status_code == 403
    assert SCOPE_REMOTE_USE in denied.text
    assert allowed.status_code == 200

    malformed_calls = _RemoteTerminalCalls(malformed="list_persistent_shells")
    malformed_client = _remote_terminal_client(
        monkeypatch, tmp_path / "malformed", malformed_calls
    )
    malformed = malformed_client.get(
        "/api/ui/terminals", params={"machine": "edge"}
    )
    assert malformed.status_code == 502

    offline_calls = _RemoteTerminalCalls()
    offline_client = _remote_terminal_client(
        monkeypatch, tmp_path / "offline", offline_calls, status="offline"
    )
    offline = offline_client.get(
        "/api/ui/terminals", params={"machine": "edge"}
    )
    assert offline.status_code == 503
    assert offline_calls.calls == []


def test_remote_terminal_websocket_uses_selected_machine(monkeypatch, tmp_path):
    calls = _RemoteTerminalCalls()
    client = _remote_terminal_client(
        monkeypatch, tmp_path, calls, auth_mode="oauth"
    )
    scope = f"{SCOPE_SHELL_READ} {SCOPE_SHELL_EXECUTE} {SCOPE_REMOTE_USE}"
    bearer = _bearer_protocol(scope)

    with client.websocket_connect(
        "/ui/ws/terminals/shared?machine=edge&lines=50",
        subprotocols=["lsm-ui-terminal", bearer],
    ) as websocket:
        assert websocket.receive_json() == {
            "type": "snapshot",
            "machine": "edge",
            "shell_id": "shared",
            "output": "\x1b[36medge$ \x1b[0m",
        }
        websocket.send_json(
            {"type": "input", "data": "echo edge", "enter": True}
        )
        websocket.send_json({"type": "resize", "cols": 100, "rows": 30})
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {
            "type": "pong",
            "machine": "edge",
            "shell_id": "shared",
        }
        websocket.send_json({"type": "close"})

    tools = [tool for _, tool, _, _ in calls.calls]
    assert tools[0] == "list_persistent_shells"
    assert "read_persistent_shell_output" in tools
    assert "send_persistent_shell_input" in tools
    assert "resize_persistent_shell" in tools
    assert all("session_id" not in args for _, _, args, _ in calls.calls)
    read_args = [
        args
        for _, tool, args, _ in calls.calls
        if tool == "read_persistent_shell_output"
    ]
    assert read_args
    assert all(args.get("preserve_ansi") is True for args in read_args)


def test_remote_terminal_websocket_requires_remote_scope(monkeypatch, tmp_path):
    calls = _RemoteTerminalCalls()
    client = _remote_terminal_client(
        monkeypatch, tmp_path, calls, auth_mode="oauth"
    )
    bearer = _bearer_protocol(f"{SCOPE_SHELL_READ} {SCOPE_SHELL_EXECUTE}")

    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(
            "/ui/ws/terminals/shared?machine=edge",
            subprotocols=["lsm-ui-terminal", bearer],
        ),
    ):
        pass

    assert exc_info.value.code == 4403
    assert calls.calls == []


def test_remote_terminal_rejects_malformed_envelope_and_oversized_output():
    with pytest.raises(RuntimeError, match="malformed terminal envelope"):
        terminal_module._remote_result_data([], machine="edge", tool="list")

    oversized = {
        "shell_id": "shared",
        "output": "x" * (terminal_module.UI_TERMINAL_OUTPUT_MAX_BYTES + 1),
    }

    with pytest.raises(RuntimeError, match="oversized terminal output"):
        terminal_module._normalize_read("edge", "shared", 50, oversized)
