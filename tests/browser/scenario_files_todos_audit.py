from __future__ import annotations

import time

from playwright.sync_api import Route, expect

from tests.browser.harness import TOKEN_STORAGE_KEY, BrowserHarness


def _file_entry(harness: BrowserHarness, path: str):
    return harness.page.locator(f'.file-entry[title="{path}"]')


def run_files_todos_audit(harness: BrowserHarness) -> None:
    page = harness.page
    harness.navigate("files")

    expect(_file_entry(harness, "notes.txt")).to_be_visible()
    _file_entry(harness, "notes.txt").click()
    expect(page.locator("#file-preview-body")).to_contain_text(
        "local browser fixture"
    )
    page.locator("#file-edit").click()
    expect(page.locator("#file-editor-form")).to_be_visible()
    page.locator("#file-editor").fill("edited by Chromium\n")
    page.locator("#file-editor-form").get_by_role(
        "button", name="Save file"
    ).click()
    expect(page.locator("#file-state")).to_contain_text("Saved local:notes.txt")
    assert harness.control_workspace.joinpath("notes.txt").read_text() == (
        "edited by Chromium\n"
    )

    delayed = False

    def delay_stale_preview(route: Route) -> None:
        nonlocal delayed
        if "stale-local.txt" in route.request.url and not delayed:
            delayed = True
            time.sleep(0.4)
        route.continue_()

    page.route("**/api/ui/files/preview**", delay_stale_preview)
    _file_entry(harness, "stale-local.txt").click()
    _file_entry(harness, "notes.txt").click()
    expect(page.locator("#file-preview-body")).to_contain_text(
        "edited by Chromium"
    )
    page.wait_for_timeout(600)
    expect(page.locator("#file-preview-body")).not_to_contain_text(
        "stale local preview"
    )
    page.unroute("**/api/ui/files/preview**", delay_stale_preview)

    _file_entry(harness, "copy-source.txt").click()
    page.once("dialog", lambda dialog: dialog.accept("copied.txt"))
    page.locator("#file-copy").click()
    expect(_file_entry(harness, "copied.txt")).to_be_visible()

    page.once("dialog", lambda dialog: dialog.accept("moved.txt"))
    page.locator("#file-move").click()
    expect(_file_entry(harness, "moved.txt")).to_be_visible()
    assert not harness.control_workspace.joinpath("copied.txt").exists()

    page.once("dialog", lambda dialog: dialog.accept("renamed.txt"))
    page.locator("#file-rename").click()
    expect(_file_entry(harness, "renamed.txt")).to_be_visible()
    assert harness.control_workspace.joinpath("renamed.txt").read_text() == (
        "copy source\n"
    )

    session = harness.api("POST", "/tools/session_start", body={"workdir": "."})
    assert session["status"] == 200
    session_id = session["payload"]["session_id"]
    harness.navigate("sessions")
    page.locator("#session-refresh").click()
    expect(
        page.locator(
            f'#session-list .session-entry[data-session-id="{session_id}"]'
        )
    ).to_have_attribute("aria-current", "true")

    page.locator("#todo-add").click()
    row = page.locator("#todo-list .todo-row").last
    row.locator("input").fill("verify browser todos")
    row.locator("select").nth(0).select_option("in_progress")
    row.locator("select").nth(1).select_option("high")

    page.locator("#todo-add").click()
    rows = page.locator("#todo-list .todo-row")
    expect(rows).to_have_count(2)
    second_row = rows.last
    second_row.locator("input").fill("remove browser todo")
    for selector, index in [
        ("input", 0),
        ("select", 0),
        ("select", 1),
        ("button", 0),
    ]:
        first_box = rows.nth(0).locator(selector).nth(index).bounding_box()
        second_box = rows.nth(1).locator(selector).nth(index).bounding_box()
        assert first_box is not None and second_box is not None
        assert abs(first_box["x"] - second_box["x"]) < 1
    second_row.get_by_role("button", name="Remove").click()
    expect(rows).to_have_count(1)

    page.locator("#todo-save").click()
    expect(page.locator("#todo-state")).to_contain_text(f"Saved {session_id}")
    local_todos = harness.api(
        "GET", f"/api/ui/todos?machine=local&session_id={session_id}"
    )
    assert local_todos["status"] == 200
    assert local_todos["payload"]["data"]["todos"][0]["content"] == (
        "verify browser todos"
    )

    audited_write = harness.api(
        "POST",
        "/tools/write_file",
        body={
            "session_id": session_id,
            "path": "audit-scope.txt",
            "content": "scope protected\n" + "payload-e2e-" * 2_000,
            "overwrite": True,
        },
    )
    assert audited_write["status"] == 200

    page.locator("#session-audit-operation").select_option("files")
    page.locator("#session-audit-search").fill("write_file")
    page.locator("#session-audit-refresh").click()
    expect(
        page.locator("#session-audit-list .audit-entry").first
    ).to_be_visible()
    page.locator("#session-audit-list .audit-entry").first.click()
    expect(page.locator("#session-audit-detail-body")).to_contain_text(
        "audit-scope.txt"
    )
    expect(page.locator("#session-audit-detail-body")).to_contain_text(
        "payload-e2e-"
    )

    harness.navigate("audit")
    page.locator("#audit-operation").select_option("files")
    page.locator("#audit-search").fill("write_file")
    page.locator("#audit-refresh").click()
    expect(page.locator("#audit-list .audit-entry").first).to_be_visible()
    page.locator("#audit-list .audit-entry").first.click()
    expect(page.locator("#audit-detail-body")).to_contain_text(
        "audit-scope.txt"
    )

    full_token = page.evaluate(
        "key => sessionStorage.getItem(key)", TOKEN_STORAGE_KEY
    )
    assert isinstance(full_token, str) and full_token
    read_only_token = harness.issue_token("audit:read shell:read remote:use")
    harness.set_token(read_only_token)
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#connection-state")).to_have_text("Connected")
    harness.navigate("sessions")
    page.locator("#session-audit-operation").select_option("files")
    page.locator("#session-audit-search").fill("write_file")
    page.locator("#session-audit-refresh").click()
    expect(
        page.locator("#session-audit-list .audit-entry").first
    ).to_be_visible()
    page.locator("#session-audit-list .audit-entry").first.click()
    expect(page.locator("#session-audit-detail-meta")).to_have_text(
        "Details unavailable"
    )
    expect(page.locator("#session-audit-detail-body")).to_contain_text(
        "shell:write"
    )
    harness.console_errors = [
        line for line in harness.console_errors if "403 (Forbidden)" not in line
    ]

    harness.set_token(full_token)
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#connection-state")).to_have_text("Connected")
    harness.navigate("sessions")
    expect(
        page.locator(
            f'#session-list .session-entry[data-session-id="{session_id}"]'
        )
    ).to_have_attribute("aria-current", "true")
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#session-terminate").click()
    expect(page.locator("#session-detail-status")).to_contain_text(
        "Immediate termination requested"
    )
    blocked = harness.api(
        "POST",
        "/tools/read",
        body={"session_id": session_id, "path": "notes.txt"},
    )
    assert blocked["status"] == 409
    assert blocked["payload"]["error"] == "session_termination_requested"
    harness.console_errors = [
        line for line in harness.console_errors if "409 (Conflict)" not in line
    ]
