from __future__ import annotations

from playwright.sync_api import expect

from tests.browser.harness import BrowserHarness


def _assert_no_horizontal_overflow(harness: BrowserHarness) -> None:
    metrics = harness.page.evaluate(
        """
        () => ({
          body: document.body.scrollWidth,
          document: document.documentElement.scrollWidth,
          viewport: window.innerWidth,
        })
        """
    )
    assert metrics["body"] <= metrics["viewport"] + 1
    assert metrics["document"] <= metrics["viewport"] + 1


def run_opentui_responsive(harness: BrowserHarness) -> None:
    page = harness.page

    expect(page.locator("#opentui-panel")).to_be_visible()
    page.locator("#opentui-start").click()
    expect(page.locator("#opentui-state")).to_have_text(
        "OpenTUI running", timeout=20_000
    )
    expect(page.locator("#opentui-terminal .xterm")).to_be_visible()
    page.get_by_label("OpenTUI shortcut keys").get_by_role(
        "button", name="Tab", exact=True
    ).click()
    page.set_viewport_size({"width": 1024, "height": 760})
    _assert_no_horizontal_overflow(harness)
    page.locator("#opentui-stop").click()
    expect(page.locator("#opentui-state")).to_have_text("Stopped")

    harness.opentui_crash_marker.write_text("crash once\n", encoding="utf-8")
    page.locator("#opentui-start").click()
    expect(page.locator("#opentui-state")).to_have_text(
        "OpenTUI exited; reconnecting", timeout=10_000
    )
    expect(page.locator("#opentui-state")).to_have_text(
        "OpenTUI running", timeout=20_000
    )
    page.locator("#opentui-stop").click()
    expect(page.locator("#opentui-state")).to_have_text("Stopped")

    page.set_viewport_size({"width": 390, "height": 844})
    _assert_no_horizontal_overflow(harness)
    for selector in (
        "#dashboard-panel",
        "#remotes-panel",
        "#terminal-panel",
        "#file-panel",
        "#session-panel",
        "#audit-panel",
        "#opentui-panel",
    ):
        expect(page.locator(selector)).to_be_visible()

    page.locator("#refresh").focus()
    expect(page.locator("#refresh")).to_be_focused()
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement !== document.body")
    page.locator("#file-path").focus()
    page.keyboard.type(".")
    expect(page.locator("#file-path")).to_be_focused()
    page.locator("#file-list").hover()
    page.mouse.wheel(0, 600)

    page.set_viewport_size({"width": 1440, "height": 1000})
    _assert_no_horizontal_overflow(harness)
