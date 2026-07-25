from __future__ import annotations

from playwright.sync_api import expect

from tests.browser.harness import BrowserHarness


def run_auth_dashboard(harness: BrowserHarness) -> None:
    harness.login()
    page = harness.page

    expect(page.locator("#version")).not_to_have_text("—")
    expect(page.locator("#dashboard-version")).not_to_have_text("—")
    expect(page.locator("#dashboard-platform")).not_to_have_text("—")
    expect(page.locator("#dashboard-python")).not_to_have_text("—")
    expect(page.locator("#dashboard-machine")).to_have_value("local")
    expect(page.locator("#dashboard-state")).to_contain_text("local")

    bootstrap = harness.api("GET", "/api/ui/bootstrap")
    assert bootstrap["status"] == 200
    data = bootstrap["payload"]["data"]
    assert data["ui"]["auth_mode"] == "oauth"
    assert data["machines"][0]["name"] == "local"
    assert data["machines"][0]["status"] == "online"
    assert data["version"]

    dashboard = harness.api("GET", "/api/ui/dashboard?machine=local")
    assert dashboard["status"] == 200
    snapshot = dashboard["payload"]["data"]
    assert snapshot["machine"] == "local"
    assert snapshot["version"]["version"]
    assert snapshot["version"]["python"]
