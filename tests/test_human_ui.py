import base64
import hashlib
import html
import json
import os
import re
import stat
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import local_shell_mcp.server.http.human_ui as human_ui_module
from local_shell_mcp.config.settings import Settings, clear_settings_cache
from local_shell_mcp.executors.http.app import build_http_app
from local_shell_mcp.oauth.core.models import _CLIENTS, _CODES
from local_shell_mcp.ui.security import (
    UI_LOCAL_TOKEN_HEADER,
    get_or_create_ui_local_token,
)


@pytest.fixture(autouse=True)
def _reset_human_ui_state():
    _CLIENTS.clear()
    _CODES.clear()
    clear_settings_cache()
    yield
    _CLIENTS.clear()
    _CODES.clear()
    clear_settings_cache()


def _configure_ui(monkeypatch, tmp_path, *, auth_mode="none", **values):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", auth_mode)
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_TUI_COMMAND", "test-opentui")
    for name, value in values.items():
        monkeypatch.setenv(
            f"LOCAL_SHELL_MCP_{name.upper()}", str(value).lower()
        )
    clear_settings_cache()


def test_ui_path_normalization_and_reserved_paths():
    assert Settings(ui_path="/console/").ui_path == "/console"
    assert Settings(ui_path="//human//ui//").ui_path == "/human/ui"

    for value in (
        "ui",
        "/",
        "/../ui",
        "/api",
        "/api/custom",
        "/ui?x=1",
        '/ui"><script>',
        "/控制台",
    ):
        with pytest.raises(ValidationError):
            Settings(ui_path=value)


def test_human_ui_shell_is_public_but_api_requires_oauth(monkeypatch, tmp_path):
    _configure_ui(monkeypatch, tmp_path, auth_mode="oauth")
    client = TestClient(build_http_app(), client=("203.0.113.10", 50000))

    index = client.get("/ui")
    assert index.status_code == 200
    assert "Human Interface" in index.text
    assert 'id="dashboard-panel"' in index.text
    assert 'id="dashboard-machine"' in index.text
    assert 'id="dashboard-cpu-trend"' in index.text
    assert 'id="dashboard-alerts"' in index.text
    assert 'id="dashboard-activity"' in index.text
    assert 'id="remotes-panel"' in index.text
    assert 'id="remote-invite-dialog"' in index.text
    assert 'id="remote-invite-result-dialog"' in index.text
    assert 'id="remote-rename-dialog"' in index.text
    assert 'id="remote-revoke-dialog"' in index.text
    assert 'id="terminal-machine"' in index.text
    assert 'id="terminal-xterm"' in index.text
    assert 'id="terminal-latest"' in index.text
    assert 'id="terminal-keyboard"' in index.text
    assert 'data-terminal-key="ctrl-c"' in index.text

    assert "assets/xterm.css" in index.text
    assert "assets/xterm_bundle.js" in index.text
    assert "assets/terminal_renderer.js" in index.text
    assert "assets/opentui_console.js" in index.text
    assert 'id="opentui-panel"' in index.text
    assert 'id="opentui-terminal"' in index.text
    assert 'id="file-panel"' in index.text
    assert 'id="file-machine"' in index.text
    assert 'id="file-editor-form"' in index.text
    assert 'id="file-copy"' in index.text
    assert 'id="file-move"' in index.text
    assert 'id="file-rename"' in index.text
    assert "__LSM_UI_PATH__" not in index.text
    assert index.headers["cache-control"] == "no-store"
    csp = index.headers["content-security-policy"]
    assert "script-src 'self' 'wasm-unsafe-eval'" in csp
    assert "'unsafe-eval'" not in csp
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert "frame-ancestors 'none'" in csp
    assert client.get("/ui/callback?code=example").status_code == 200
    renderer = client.get("/ui/assets/terminal_renderer.js")
    assert renderer.status_code == 200
    assert renderer.headers["x-content-type-options"] == "nosniff"
    assert "LsmTerminalRenderer" in renderer.text
    assert "MAX_RUNS = 10_000" in renderer.text
    assert "createTextNode" in renderer.text
    assert "innerHTML" not in renderer.text

    xterm_bundle = client.get("/ui/assets/xterm_bundle.js")
    assert xterm_bundle.status_code == 200
    assert xterm_bundle.headers["x-content-type-options"] == "nosniff"
    assert "LsmXterm" in xterm_bundle.text
    assert "createImageAddon" in xterm_bundle.text
    assert "WEB_IMAGE_ADDON_OPTIONS" in xterm_bundle.text
    assert "sourceMappingURL" not in xterm_bundle.text
    assert client.get("/ui/assets/xterm.css").status_code == 200
    web_css = client.get("/ui/assets/web.css")
    assert web_css.status_code == 200
    assert "scrollbar-width: none !important" in web_css.text
    assert ".terminal-xterm .xterm-viewport::-webkit-scrollbar" in web_css.text
    license_text = client.get("/ui/assets/xterm.LICENSE.txt")
    assert license_text.status_code == 200
    assert "Permission is hereby granted" in license_text.text
    assert "@xterm/xterm 5.5.0" in license_text.text
    assert "@xterm/addon-fit 0.10.0" in license_text.text
    assert "@xterm/addon-image 0.8.0" in license_text.text
    opentui_script = client.get("/ui/assets/opentui_console.js")
    assert opentui_script.status_code == 200
    assert opentui_script.headers["x-content-type-options"] == "nosniff"
    assert "createImageAddon" in opentui_script.text
    assert opentui_script.text.index("loadAddon(api.createImageAddon())") < (
        opentui_script.text.index("fitAddon = new api.FitAddon()")
    )
    script = client.get("/ui/assets/web.js")
    assert script.status_code == 200
    assert script.headers["x-content-type-options"] == "nosniff"
    assert 'code_challenge_method", "S256"' in script.text
    assert "crypto.subtle.digest" in script.text
    assert 'resource: String(oauth.resource || "")' in script.text
    assert "pending.redirectUri === callbackUrl()" in script.text
    assert "OAuth issuer verification failed" in script.text
    assert "response.status === 401" in script.text
    assert (
        "response.status === 401 || response.status === 403" not in script.text
    )
    assert "payload.message || payload.detail" in script.text
    assert "dashboardGeneration" in script.text
    assert "requestedMachine !== dashboardMachine" in script.text
    assert "refreshDashboardInBackground" in script.text
    assert "request(dashboardQueryPath())" in script.text
    assert "createElementNS" in script.text
    assert "dashboardNumber" in script.text
    assert "remoteGeneration" in script.text
    assert "generation !== remoteGeneration" in script.text
    assert "startRemotePolling" in script.text
    assert "clearRemoteInviteResult" in script.text
    assert "navigator.clipboard.writeText(remoteInviteCommand)" in script.text
    assert 'remoteInviteCommand = ""' in script.text
    assert "innerHTML" not in script.text
    assert "terminalMachineStates" in script.text
    assert "requestedMachine !== terminalMachine" in script.text
    assert 'url.searchParams.set("machine", machine)' in script.text
    assert 'url.searchParams.set("mode", "auto")' in script.text
    assert 'socket.binaryType = "arraybuffer"' in script.text
    assert "terminalReady" in script.text
    assert "activateTerminalMode" in script.text
    assert "sendTerminalBytes" in script.text
    assert "offset += 65536" in script.text
    assert "registerOscHandler(8" in script.text
    assert "createImageAddon" in script.text
    assert script.text.index("loadAddon(api.createImageAddon())") < (
        script.text.index("terminalFitAddon = new api.FitAddon()")
    )
    assert "allowNonHttpProtocols: false" in script.text
    assert "terminalSocketMachine === terminalMachine" in script.text
    assert "bridge_id" not in script.text
    assert "acceptTerminalSnapshot" in script.text
    assert "terminalPendingOutput" in script.text
    assert "terminalSpecialKeys" in script.text
    assert "navigateTerminalHistory" in script.text
    assert "LsmTerminalRenderer" in script.text
    assert "filePreviewGeneration" in script.text
    assert "generation !== filePreviewGeneration" in script.text
    assert "fileListGeneration" in script.text
    assert "requestedMachine !== fileMachine" in script.text
    assert 'fileQuery("/files/preview"' in script.text
    assert "machine: fileMachine" in script.text
    assert "renderFileMachines" in script.text
    assert "fileMutations" in script.text
    assert 'fileAction("copy"' in script.text
    assert 'fileAction("move"' in script.text
    assert 'fileAction("rename"' in script.text
    protected = client.get("/api/ui/bootstrap")
    assert protected.status_code == 401


def test_browser_oauth_pkce_flow_reaches_authenticated_ui(
    monkeypatch, tmp_path
):
    base_url = "https://local-shell-mcp.example"
    admin_pin = "12345678"
    _CLIENTS.clear()
    _CODES.clear()
    _configure_ui(
        monkeypatch,
        tmp_path,
        auth_mode="oauth",
        base_url=base_url,
        oauth_admin_pin=admin_pin,
    )
    client = TestClient(
        build_http_app(),
        base_url=base_url,
        client=("203.0.113.10", 50000),
    )

    index = client.get("/ui")
    match = re.search(r'data-lsm-config="([^"]+)"', index.text)
    assert match is not None
    runtime = json.loads(html.unescape(match.group(1)))
    assert runtime["oauth"] == {
        "issuer": base_url,
        "resource": f"{base_url}/mcp",
        "scope": (
            "shell:read shell:write shell:execute git:write "
            "file:share remote:use audit:read audit:full"
        ),
        "registrationEndpoint": "/oauth/register",
        "authorizationEndpoint": "/oauth/authorize",
        "tokenEndpoint": "/oauth/token",
    }

    callback = f"{base_url}/ui/callback"
    registration = client.post(
        "/oauth/register",
        json={
            "client_name": "local-shell-mcp WebUI",
            "redirect_uris": [callback],
        },
    )
    assert registration.status_code == 201
    client_id = registration.json()["client_id"]

    verifier = "browser-pkce-verifier-" + "x" * 48
    challenge = (
        base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    state = "browser-oauth-state"
    authorization = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": callback,
        "scope": runtime["oauth"]["scope"],
        "resource": runtime["oauth"]["resource"],
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    approval_page = client.get("/oauth/authorize", params=authorization)
    assert approval_page.status_code == 200
    assert ">Approve<" in approval_page.text

    approved = client.post(
        "/oauth/authorize",
        data={**authorization, "pin": admin_pin},
        follow_redirects=False,
    )
    assert approved.status_code == 302
    redirect = urlparse(approved.headers["location"])
    query = parse_qs(redirect.query)
    assert f"{redirect.scheme}://{redirect.netloc}{redirect.path}" == callback
    assert query["state"] == [state]
    assert query["iss"] == [runtime["oauth"]["issuer"]]
    assert client.get(approved.headers["location"]).status_code == 200

    exchange = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": query["code"][0],
            "client_id": client_id,
            "redirect_uri": callback,
            "resource": runtime["oauth"]["resource"],
            "code_verifier": verifier,
        },
    )
    assert exchange.status_code == 200
    token = exchange.json()["access_token"]
    bootstrap = client.get(
        "/api/ui/bootstrap", headers={"Authorization": f"Bearer {token}"}
    )
    assert bootstrap.status_code == 200
    assert bootstrap.json()["data"]["machines"][0]["name"] == "local"


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
    if os.name != "nt":
        assert stat.S_IMODE(token_path.stat().st_mode) == 0o600


def test_human_ui_custom_mount_and_bootstrap(monkeypatch, tmp_path):
    _configure_ui(monkeypatch, tmp_path, ui_path="/control")
    client = TestClient(build_http_app())

    assert client.get("/ui").status_code == 404
    index = client.get("/control")
    assert index.status_code == 200
    assert 'href="/control/assets/web.css"' in index.text
    assert 'src="/control/assets/syntax_highlight.js"' in index.text
    match = re.search(r'data-lsm-config="([^"]+)"', index.text)
    assert match is not None
    runtime = json.loads(html.unescape(match.group(1)))
    assert runtime["oauth"] is None
    assert runtime["wallpaper"] == "aurora"

    payload = client.get("/api/ui/bootstrap").json()["data"]
    assert payload["ui"] == {
        "path": "/control",
        "api_prefix": "/api/ui",
        "auth_mode": "none",
        "features": {
            "dashboard": True,
            "remote_dashboard": True,
            "machines": True,
            "remotes": True,
            "terminals": True,
            "remote_terminals": True,
            "terminal_websocket": True,
            "files": True,
            "file_preview": True,
            "syntax_highlighting": True,
            "audit_image_preview": True,
            "wallpaper": "aurora",
            "opentui": True,
            "file_editor": True,
            "file_copy": True,
            "file_move": True,
            "file_rename": True,
            "remote_files": True,
            "remote_file_editor": True,
            "todos": True,
            "remote_todos": True,
            "audit": True,
            "remote_audit": True,
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
