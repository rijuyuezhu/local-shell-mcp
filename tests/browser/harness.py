from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    expect,
)

from tests.e2e_helpers import PROJECT_ROOT, SRC_ROOT, free_tcp_port, server_env

TOKEN_STORAGE_KEY = "local-shell-mcp-ui-access-token"


def _start_logged_process(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
) -> subprocess.Popen[bytes]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        return subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            stdout=stdout,
            stderr=stderr,
        )


def _terminate_process(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _wait_for_http_ready(base_url: str, process: subprocess.Popen[Any]) -> None:
    deadline = time.monotonic() + 15
    with httpx.Client(timeout=1) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(
                    f"server exited early with code {process.returncode}"
                )
            try:
                response = client.get(f"{base_url}/healthz")
                if (
                    response.status_code == 200
                    and response.json().get("ok") is True
                ):
                    return
            except httpx.HTTPError, json.JSONDecodeError:
                pass
            time.sleep(0.05)
    raise AssertionError(f"server did not become ready at {base_url}")


def _worker_env(workspace: Path, tmux_tmpdir: Path) -> dict[str, str]:
    env = os.environ.copy()
    pythonpath = str(SRC_ROOT)
    if env.get("PYTHONPATH"):
        pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
    env.update(
        {
            "PYTHONPATH": pythonpath,
            "TMUX_TMPDIR": str(tmux_tmpdir),
            "LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(workspace),
            "LOCAL_SHELL_MCP_STATE_DIR": str(workspace / ".local-shell-mcp"),
            "LOCAL_SHELL_MCP_WORKER_STATE_DIR": str(
                workspace / ".local-shell-mcp-worker"
            ),
            "LOCAL_SHELL_MCP_AUTH_MODE": "none",
            "LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED": "false",
            "LOCAL_SHELL_MCP_RUN_SHELL_DEFAULT_TIMEOUT_S": "5",
            "LOCAL_SHELL_MCP_RUN_SHELL_MAX_TIMEOUT_S": "10",
            "LOCAL_SHELL_MCP_TOOL_TIMEOUT_S": "20",
        }
    )
    return env


def _invite_code(command: str) -> str:
    argv = shlex.split(command)
    for index, value in enumerate(argv[:-1]):
        if value == "--invite":
            return argv[index + 1]
    match = re.search(r"--invite(?:=|\s+)([^\s'\"]+)", command)
    if match:
        return match.group(1)
    raise AssertionError(f"unable to parse invite code from command: {command}")


@dataclass
class BrowserHarness:
    root: Path
    artifacts: Path
    control_workspace: Path
    remote_workspace: Path
    control_tmux_tmpdir: Path
    remote_tmux_tmpdir: Path
    base_url: str
    admin_pin: str
    opentui_crash_marker: Path
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page
    server: subprocess.Popen[Any]
    worker: subprocess.Popen[Any] | None = None
    terminal_sessions: list[tuple[str, str]] = field(default_factory=list)
    console_messages: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    request_failures: list[str] = field(default_factory=list)
    websocket_events: list[str] = field(default_factory=list)

    @classmethod
    def start(
        cls,
        root: Path,
        artifacts: Path,
        playwright: Playwright,
    ) -> BrowserHarness:
        artifacts.mkdir(parents=True, exist_ok=True)
        control_workspace = root / "workspace-control"
        remote_workspace = root / "workspace-remote"
        control_workspace.mkdir(parents=True)
        remote_workspace.mkdir(parents=True)
        control_tmux_tmpdir = Path(tempfile.mkdtemp(prefix="lsm-b-ctl-"))
        remote_tmux_tmpdir = Path(tempfile.mkdtemp(prefix="lsm-b-rem-"))
        (control_workspace / "notes.txt").write_text(
            "local browser fixture\n", encoding="utf-8"
        )
        (control_workspace / "stale-local.txt").write_text(
            "stale local preview\n", encoding="utf-8"
        )
        (control_workspace / "copy-source.txt").write_text(
            "copy source\n", encoding="utf-8"
        )
        (remote_workspace / "remote-note.txt").write_text(
            "remote browser fixture\n", encoding="utf-8"
        )
        opentui_crash_marker = root / "opentui-crash-next"
        opentui_wrapper = root / "opentui-wrapper.py"
        opentui_binary = (
            PROJECT_ROOT / "ui-opentui" / "dist" / "local-shell-mcp-tui"
        )
        opentui_wrapper.write_text(
            "#!/usr/bin/env python3\n"
            "import os\n"
            "from pathlib import Path\n"
            f"marker = Path({str(opentui_crash_marker)!r})\n"
            f"binary = {str(opentui_binary)!r}\n"
            "if marker.exists():\n"
            "    marker.unlink()\n"
            "    print('intentional browser e2e OpenTUI crash', flush=True)\n"
            "    raise SystemExit(17)\n"
            "os.execv(binary, [binary])\n",
            encoding="utf-8",
        )
        opentui_wrapper.chmod(0o755)

        port = free_tcp_port()
        base_url = f"http://127.0.0.1:{port}"
        admin_pin = "browser-e2e-pin-924681"
        env = server_env(control_workspace, mode="http", port=port)
        env.update(
            {
                "TMUX_TMPDIR": str(control_tmux_tmpdir),
                "LOCAL_SHELL_MCP_AUTH_MODE": "oauth",
                "LOCAL_SHELL_MCP_BASE_URL": base_url,
                "LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN": admin_pin,
                "LOCAL_SHELL_MCP_REMOTE_ENABLED": "true",
                "LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S": "1",
                "LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S": "20",
                "LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED": "false",
                "LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S": "120",
                "LOCAL_SHELL_MCP_UI_TUI_COMMAND": str(opentui_wrapper),
            }
        )
        server = _start_logged_process(
            [
                sys.executable,
                "-m",
                "local_shell_mcp.main",
                "--mode",
                "http",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--auth-mode",
                "oauth",
                "--workspace-root",
                str(control_workspace),
                "--agent-bridge-enabled",
                "false",
                "--remote-enabled",
                "true",
                "--remote-poll-timeout-s",
                "1",
                "--remote-job-timeout-s",
                "20",
            ],
            cwd=PROJECT_ROOT,
            env=env,
            stdout_path=artifacts / "server.stdout.log",
            stderr_path=artifacts / "server.stderr.log",
        )
        try:
            _wait_for_http_ready(base_url, server)
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000},
                record_video_dir=str(artifacts / "video"),
            )
            context.set_default_timeout(15_000)
            context.tracing.start(
                screenshots=True, snapshots=True, sources=True
            )
            page = context.new_page()
            harness = cls(
                root=root,
                artifacts=artifacts,
                control_workspace=control_workspace,
                remote_workspace=remote_workspace,
                control_tmux_tmpdir=control_tmux_tmpdir,
                remote_tmux_tmpdir=remote_tmux_tmpdir,
                base_url=base_url,
                admin_pin=admin_pin,
                opentui_crash_marker=opentui_crash_marker,
                playwright=playwright,
                browser=browser,
                context=context,
                page=page,
                server=server,
            )
            harness._attach_diagnostics()
            return harness
        except Exception:
            _terminate_process(server)
            shutil.rmtree(control_tmux_tmpdir, ignore_errors=True)
            shutil.rmtree(remote_tmux_tmpdir, ignore_errors=True)
            raise

    def _attach_diagnostics(self) -> None:
        def on_console(message: Any) -> None:
            line = f"{message.type}: {message.text}"
            self.console_messages.append(line)
            if message.type == "error":
                self.console_errors.append(line)

        def on_websocket(socket: Any) -> None:
            self.websocket_events.append(f"open {socket.url}")

            def record_frame(direction: str, frame: Any) -> None:
                payload = frame
                if isinstance(frame, dict):
                    payload = frame.get("payload", frame)
                if isinstance(payload, bytes):
                    display = payload[:256].hex()
                else:
                    display = str(payload)[:2048]
                self.websocket_events.append(
                    f"{direction} {socket.url} {display}"
                )

            socket.on("framesent", lambda frame: record_frame("sent", frame))
            socket.on(
                "framereceived", lambda frame: record_frame("received", frame)
            )
            socket.on(
                "close",
                lambda: self.websocket_events.append(f"close {socket.url}"),
            )

        self.page.on("console", on_console)
        self.page.on("websocket", on_websocket)
        self.page.on(
            "pageerror", lambda error: self.page_errors.append(str(error))
        )
        self.page.on(
            "requestfailed",
            lambda request: self.request_failures.append(
                f"{request.method} {request.url}: {request.failure}"
            ),
        )

    def stop(self, *, failed: bool) -> None:
        try:
            if failed and not self.page.is_closed():
                self.page.screenshot(
                    path=str(self.artifacts / "failure.png"), full_page=True
                )
            if not self.page.is_closed():
                for machine, shell_id in reversed(self.terminal_sessions):
                    with contextlib.suppress(Exception):
                        self.api(
                            "POST",
                            "/api/ui/terminals/kill",
                            body={"machine": machine, "shell_id": shell_id},
                        )
        finally:
            (self.artifacts / "browser-console.log").write_text(
                "\n".join(self.console_messages), encoding="utf-8"
            )
            (self.artifacts / "page-errors.log").write_text(
                "\n".join(self.page_errors), encoding="utf-8"
            )
            (self.artifacts / "request-failures.log").write_text(
                "\n".join(self.request_failures), encoding="utf-8"
            )
            (self.artifacts / "websockets.log").write_text(
                "\n".join(self.websocket_events), encoding="utf-8"
            )
            with contextlib.suppress(Exception):
                self.context.tracing.stop(
                    path=str(self.artifacts / "trace.zip")
                )
            with contextlib.suppress(Exception):
                self.context.close()
            with contextlib.suppress(Exception):
                self.browser.close()
            _terminate_process(self.worker)
            _terminate_process(self.server)
            shutil.rmtree(self.control_tmux_tmpdir, ignore_errors=True)
            shutil.rmtree(self.remote_tmux_tmpdir, ignore_errors=True)

    def track_terminal(self, machine: str, shell_id: str) -> None:
        self.terminal_sessions.append((machine, shell_id))

    def api(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.page.evaluate(
            """
            async ({method, path, body, tokenKey}) => {
              const token = sessionStorage.getItem(tokenKey) || "";
              const headers = token ? {Authorization: `Bearer ${token}`} : {};
              if (body !== null) headers["Content-Type"] = "application/json";
              const response = await fetch(path, {
                method,
                headers,
                body: body === null ? undefined : JSON.stringify(body),
              });
              let payload = null;
              try { payload = await response.json(); } catch (_) {}
              return {status: response.status, payload};
            }
            """,
            {
                "method": method,
                "path": path,
                "body": body,
                "tokenKey": TOKEN_STORAGE_KEY,
            },
        )
        assert isinstance(result, dict)
        return result

    def issue_token(self, scope: str) -> str:
        callback = f"{self.base_url}/ui/callback"
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode("ascii")).digest()
            )
            .rstrip(b"=")
            .decode("ascii")
        )
        state = secrets.token_urlsafe(24)
        resource = f"{self.base_url}/mcp"
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            registration = client.post(
                f"{self.base_url}/oauth/register",
                json={
                    "client_name": "browser-e2e-scope-client",
                    "redirect_uris": [callback],
                },
            )
            registration.raise_for_status()
            client_id = registration.json()["client_id"]
            authorization = {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": callback,
                "scope": scope,
                "resource": resource,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
            }
            approved = client.post(
                f"{self.base_url}/oauth/authorize?{urlencode(authorization)}",
                data={**authorization, "pin": self.admin_pin},
            )
            assert approved.status_code == 302
            query = parse_qs(urlparse(approved.headers["location"]).query)
            assert query["state"] == [state]
            exchange = client.post(
                f"{self.base_url}/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": query["code"][0],
                    "client_id": client_id,
                    "redirect_uri": callback,
                    "resource": resource,
                    "code_verifier": verifier,
                },
            )
            exchange.raise_for_status()
            return str(exchange.json()["access_token"])

    def set_token(self, token: str) -> None:
        self.page.evaluate(
            "([key, value]) => sessionStorage.setItem(key, value)",
            [TOKEN_STORAGE_KEY, token],
        )

    def login(self) -> None:
        response = self.page.goto(
            f"{self.base_url}/ui", wait_until="domcontentloaded"
        )
        assert response is not None and response.status == 200
        expect(self.page.locator("#auth-panel")).to_be_visible()
        unauthenticated = self.api("GET", "/api/ui/bootstrap")
        assert unauthenticated["status"] == 401

        self.page.locator("#oauth-login").click()
        self.page.wait_for_url(re.compile(r"/oauth/authorize\?"))
        self.page.locator('input[name="pin"]').fill(self.admin_pin)
        self.page.get_by_role("button", name="Approve").click()
        self.page.wait_for_url(re.compile(r"/ui/callback"))
        expect(self.page.locator("#connection-state")).to_have_text("Connected")
        expect(self.page.locator("#auth-panel")).to_be_hidden()
        assert self.page.evaluate(
            "key => Boolean(sessionStorage.getItem(key))", TOKEN_STORAGE_KEY
        )
        self.console_errors = [
            line
            for line in self.console_errors
            if "401 (Unauthorized)" not in line
        ]

    def invite_and_start_worker(self, machine: str = "browser-edge") -> None:
        self.page.locator("#remote-invite-open").click()
        expect(self.page.locator("#remote-invite-dialog")).to_be_visible()
        self.page.locator("#remote-invite-name").fill(machine)
        self.page.locator("#remote-invite-workdir").fill(
            str(self.remote_workspace)
        )
        self.page.locator("#remote-invite-form").get_by_role(
            "button", name="Create invite"
        ).click()
        expect(
            self.page.locator("#remote-invite-result-dialog")
        ).to_be_visible()
        command = self.page.locator("#remote-invite-command").inner_text()
        invite = _invite_code(command)
        self.page.locator("#remote-invite-done").click()

        self.worker = _start_logged_process(
            [
                sys.executable,
                "-m",
                "local_shell_mcp.remote_worker",
                "connect",
                "--server",
                self.base_url,
                "--invite",
                invite,
                "--name",
                machine,
                "--workdir",
                str(self.remote_workspace),
            ],
            cwd=PROJECT_ROOT,
            env=_worker_env(self.remote_workspace, self.remote_tmux_tmpdir),
            stdout_path=self.artifacts / "worker.stdout.log",
            stderr_path=self.artifacts / "worker.stderr.log",
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.worker.poll() is not None:
                raise AssertionError(
                    f"worker exited early with code {self.worker.returncode}"
                )
            inventory = self.api("GET", "/api/ui/remotes")
            if inventory["status"] == 200:
                machines = inventory["payload"]["data"]["machines"]
                if any(
                    item.get("name") == machine
                    and item.get("status") == "online"
                    for item in machines
                ):
                    self.page.locator("#remote-refresh").click()
                    self.page.wait_for_timeout(300)
                    return
            time.sleep(0.1)
        raise AssertionError(f"remote worker {machine!r} did not become online")

    def assert_clean_browser(self) -> None:
        assert not self.console_errors, "\n".join(self.console_errors)
        assert not self.page_errors, "\n".join(self.page_errors)
        unexpected = [
            line
            for line in self.request_failures
            if "favicon.ico" not in line and "ERR_ABORTED" not in line
        ]
        assert not unexpected, "\n".join(unexpected)
