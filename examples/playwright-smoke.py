from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://example.com", wait_until="load")
    print(page.title())
    print(page.locator("body").inner_text())
    browser.close()
