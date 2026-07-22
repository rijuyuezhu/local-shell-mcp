from __future__ import annotations

import asyncio
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import local_shell_mcp.server.http.ui_opentui as opentui
from local_shell_mcp.config.settings import clear_settings_cache
from local_shell_mcp.server.http.app import build_http_app


@pytest.fixture(autouse=True)
def _reset_settings() -> Generator[None]:
    clear_settings_cache()
    yield
    clear_settings_cache()


def _configure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, auth: str
) -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", auth)
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_TUI_COMMAND", "fake-tui")
    clear_settings_cache()


class _FakeProcess:
    def __init__(self) -> None:
        self.reads = [b"OpenTUI ready\r\n", b""]
        self.writes: list[bytes] = []
        self.resizes: list[tuple[int, int]] = []
        self.closed = False

    def resize(self, cols: int, rows: int) -> None:
        self.resizes.append((cols, rows))

    async def read(self) -> bytes:
        await asyncio.sleep(0)
        return self.reads.pop(0)

    async def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def exit_code(self) -> int | None:
        return 0

    async def close(self) -> None:
        self.closed = True


def test_opentui_websocket_requires_oauth_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure(monkeypatch, tmp_path, auth="oauth")
    client = TestClient(build_http_app(), client=("203.0.113.10", 50000))

    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(
            "/ui/ws/opentui", subprotocols=["lsm-ui-terminal"]
        ),
    ):
        pass

    assert exc_info.value.code == 4401


def test_opentui_websocket_streams_process_output_and_closes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure(monkeypatch, tmp_path, auth="none")
    process = _FakeProcess()
    monkeypatch.setattr(
        opentui,
        "spawn_opentui_process",
        lambda cols, rows, cell_aspect: process,
    )
    client = TestClient(build_http_app())

    with client.websocket_connect(
        "/ui/ws/opentui?cols=90&rows=28&cell_aspect=2",
        subprotocols=["lsm-ui-terminal"],
    ) as websocket:
        assert websocket.receive_bytes() == b"OpenTUI ready\r\n"
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_bytes()

    assert process.closed is True


def test_spawn_opentui_process_keeps_local_token_in_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure(monkeypatch, tmp_path, auth="none")
    captured: dict[str, Any] = {}

    class FakeUnix:
        def __init__(
            self,
            command: list[str],
            env: dict[str, str],
            cols: int,
            rows: int,
        ) -> None:
            captured.update(
                command=command,
                env=env,
                cols=cols,
                rows=rows,
            )

    monkeypatch.setattr(opentui, "UnixOpenTuiProcess", FakeUnix)
    monkeypatch.setattr(opentui, "WindowsOpenTuiProcess", FakeUnix)
    monkeypatch.setattr(
        opentui, "resolve_tui_command", lambda _settings: ["fake-tui"]
    )
    monkeypatch.setattr(
        opentui, "get_or_create_ui_local_token", lambda: "private-token"
    )

    opentui.spawn_opentui_process(100, 30, 2.5)

    assert captured["command"] == ["fake-tui"]
    assert "private-token" not in captured["command"]
    assert captured["env"][opentui.UI_LOCAL_TOKEN_ENV] == "private-token"
    assert captured["env"]["LOCAL_SHELL_MCP_UI_API_BASE"].endswith(
        ":8765/api/ui"
    )
    assert captured["env"]["LOCAL_SHELL_MCP_UI_MODE"] == "web"
    assert captured["env"]["TERM"] == "xterm-256color"
    assert captured["env"]["COLORTERM"] == "truecolor"
    assert captured["env"]["TERM_PROGRAM"] == "vscode"
    assert captured["env"]["TERM_PROGRAM_VERSION"] == (
        f"local-shell-mcp/{opentui.__version__}"
    )
