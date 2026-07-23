from __future__ import annotations

import secrets
import time

from playwright.sync_api import expect

from tests.browser.harness import BrowserHarness

MACHINE = "browser-edge"


def _wait_terminal_output(
    harness: BrowserHarness,
    machine: str,
    shell_id: str,
    marker: str,
    *,
    websocket_event_start: int = 0,
) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = harness.api(
            "GET",
            f"/api/ui/terminals/read?machine={machine}&shell_id={shell_id}&lines=1000",
        )
        if result["status"] == 200:
            output = str(result["payload"]["data"].get("output") or "")
            if marker in output:
                assert any(
                    event.startswith("received ws://")
                    for event in harness.websocket_events[
                        websocket_event_start:
                    ]
                )
                return
        time.sleep(0.1)
    raise AssertionError(f"terminal output did not contain {marker!r}")


def _start_terminal(harness: BrowserHarness, name: str) -> str:
    page = harness.page
    page.locator("#terminal-name").fill(name)
    page.locator("#terminal-start-form").get_by_role(
        "button", name="New terminal"
    ).click()
    expect(page.locator("#terminal-state")).to_contain_text("Connected")
    machine = page.locator("#terminal-machine").input_value()
    inventory = harness.api(
        "GET",
        f"/api/ui/terminals?machine={machine}",
    )
    assert inventory["status"] == 200
    shells = inventory["payload"]["data"]["shells"]
    match = next(item for item in shells if item.get("shell_id") == name)
    shell_id = str(match["shell_id"])
    harness.track_terminal(machine, shell_id)
    return shell_id


def _send_terminal(
    harness: BrowserHarness,
    machine: str,
    shell_id: str,
    command: str,
    marker: str,
) -> None:
    page = harness.page
    expect(page.locator("#terminal-input")).to_be_enabled()
    websocket_event_start = len(harness.websocket_events)
    page.locator("#terminal-input").fill(command)
    page.locator("#terminal-input-form").get_by_role(
        "button", name="Send"
    ).click()
    _wait_terminal_output(
        harness,
        machine,
        shell_id,
        marker,
        websocket_event_start=websocket_event_start,
    )


def run_terminals_remote(harness: BrowserHarness) -> None:
    page = harness.page
    suffix = secrets.token_hex(4)

    local_shell = _start_terminal(harness, f"browser-local-{suffix}")
    _send_terminal(
        harness,
        "local",
        local_shell,
        "printf 'local-terminal-e2e\\n'",
        "local-terminal-e2e",
    )
    resized = harness.api(
        "POST",
        "/api/ui/terminals/resize",
        body={
            "machine": "local",
            "shell_id": local_shell,
            "cols": 111,
            "rows": 37,
        },
    )
    assert resized["status"] == 200
    assert resized["payload"]["data"]["cols"] == 111

    page.locator("#terminal-input").fill("printf '%s\\n' {1..180}")
    page.locator("#terminal-input-form").get_by_role(
        "button", name="Send"
    ).click()
    _wait_terminal_output(harness, "local", local_shell, "180")
    viewport = page.locator("#terminal-xterm .xterm-viewport")
    expect(viewport).to_be_visible()
    screen = page.locator("#terminal-xterm .xterm-screen")
    expect(screen).to_be_visible()
    before_scroll = len(harness.websocket_events)
    screen.hover()
    page.mouse.wheel(0, -1600)
    deadline = time.monotonic() + 5
    sent: list[str] = []
    while time.monotonic() < deadline:
        sent = [
            event
            for event in harness.websocket_events[before_scroll:]
            if event.startswith("sent ws://")
        ]
        if sent:
            break
        time.sleep(0.05)
    assert sent
    page.keyboard.press("End")

    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#connection-state")).to_have_text("Connected")
    session_button = page.locator(
        f'#terminal-list .terminal-session[title*="{local_shell}"]'
    )
    expect(session_button).to_be_visible()
    session_button.click()
    expect(page.locator("#terminal-state")).to_contain_text("Connected")
    expect(page.locator("#terminal-xterm .xterm")).to_be_visible()
    _wait_terminal_output(harness, "local", local_shell, "local-terminal-e2e")

    harness.invite_and_start_worker(MACHINE)
    page.locator("#refresh").click()
    expect(
        page.locator('#file-machine option[value="browser-edge"]')
    ).to_have_count(1)
    expect(
        page.locator('#terminal-machine option[value="browser-edge"]')
    ).to_have_count(1)
    expect(
        page.locator('#todo-machine option[value="browser-edge"]')
    ).to_have_count(1)

    page.locator("#file-machine").select_option(MACHINE)
    expect(page.locator("#file-state")).to_contain_text(f"{MACHINE}:.")
    remote_note = page.locator('.file-entry[title="remote-note.txt"]')
    expect(remote_note).to_be_visible()
    remote_note.click()
    expect(page.locator("#file-preview-body")).to_contain_text(
        "remote browser fixture"
    )
    page.locator("#file-edit").click()
    page.locator("#file-editor").fill("edited on remote worker\n")
    page.locator("#file-editor-form").get_by_role(
        "button", name="Save file"
    ).click()
    expect(page.locator("#file-state")).to_contain_text(
        f"Saved {MACHINE}:remote-note.txt"
    )
    assert harness.remote_workspace.joinpath("remote-note.txt").read_text() == (
        "edited on remote worker\n"
    )
    assert harness.control_workspace.joinpath("notes.txt").read_text() == (
        "edited by Chromium\n"
    )

    page.locator("#todo-machine").select_option(MACHINE)
    expect(page.locator("#todo-state")).to_contain_text(f"{MACHINE} · loaded")
    page.locator("#todo-add").click()
    remote_row = page.locator("#todo-list .todo-row").last
    remote_row.locator("input").fill("remote todo is isolated")
    page.locator("#todo-save").click()
    expect(page.locator("#todo-state")).to_contain_text(f"Saved {MACHINE}")
    remote_todos = harness.api("GET", f"/api/ui/todos?machine={MACHINE}")
    local_todos = harness.api("GET", "/api/ui/todos?machine=local")
    assert remote_todos["payload"]["data"]["todos"][0]["content"] == (
        "remote todo is isolated"
    )
    assert local_todos["payload"]["data"]["todos"][0]["content"] == (
        "verify browser todos"
    )

    page.locator("#terminal-machine").select_option(MACHINE)
    expect(page.locator("#terminal-state")).to_contain_text(
        f"0 session(s) · {MACHINE}"
    )
    remote_shell = _start_terminal(harness, f"browser-remote-{suffix}")
    _send_terminal(
        harness,
        MACHINE,
        remote_shell,
        "printf 'remote-terminal-e2e\\n'",
        "remote-terminal-e2e",
    )
    remote_resize = harness.api(
        "POST",
        "/api/ui/terminals/resize",
        body={
            "machine": MACHINE,
            "shell_id": remote_shell,
            "cols": 109,
            "rows": 35,
        },
    )
    assert remote_resize["status"] == 200
    assert remote_resize["payload"]["data"]["machine"] == MACHINE

    page.locator("#terminal-kill").click()
    expect(page.locator("#terminal-state")).to_contain_text(
        f"0 session(s) · {MACHINE}"
    )
    page.locator("#terminal-machine").select_option("local")
    page.locator(
        f'#terminal-list .terminal-session[title*="{local_shell}"]'
    ).click()
    page.locator("#terminal-kill").click()
    expect(page.locator("#terminal-state")).to_contain_text(
        "0 session(s) · local"
    )
