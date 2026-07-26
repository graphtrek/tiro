"""Screenshots every vision page into ../screenshots/ for visual review against REQUIREMENTS
"Look and feel" (Bootstrap Yeti + HTMX + DataTables, Hungarian). Also asserts no JS console errors.

Uses a cookie seeded with a locally-minted JWT (see conftest.auth_token) instead of a real
Google login, so this suite never needs a browser OAuth consent step.
"""
from pathlib import Path

import pytest

playwright_sync_api = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright_sync_api.sync_playwright

SCREENSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "screenshots"

PUBLIC_PAGES = {
    "pitch": "/",
}

PROTECTED_PAGES = {
    "dashboard": "/ui/",
    "invoices": "/ui/invoices",
    "invoice_files": "/ui/invoice-files",
    "suppliers": "/ui/suppliers",
    "customers": "/ui/customers",
    "bank": "/ui/transactions",
    "dividend": "/ui/dividend",
    "adok": "/ui/adok",
    "sync": "/ui/sync",
    "upload": "/ui/upload",
}


def _screenshot(page, url: str, out: Path) -> list[str]:
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on(
        "console",
        lambda msg: errors.append(f"console.{msg.type}: {msg.text}") if msg.type == "error" else None,
    )
    page.goto(url, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(500)
    out.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out), full_page=True)
    return errors


@pytest.fixture(scope="module")
def browser_context(auth_token, base_urls):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_cookies(
            [{"name": "mp_access_token", "value": auth_token, "domain": "localhost", "path": "/"}]
        )
        yield context, base_urls["vision"]
        browser.close()


@pytest.mark.parametrize("name,path", list(PUBLIC_PAGES.items()))
def test_public_pages_render_without_js_errors(browser_context, name, path):
    context, vision_base = browser_context
    page = context.new_page()
    errors = _screenshot(page, vision_base + path, SCREENSHOT_DIR / f"e2e_{name}.png")
    page.close()
    assert not errors, f"{name}: {errors}"


@pytest.mark.parametrize("name,path", list(PROTECTED_PAGES.items()))
def test_protected_pages_render_without_js_errors(browser_context, name, path):
    context, vision_base = browser_context
    page = context.new_page()
    errors = _screenshot(page, vision_base + path, SCREENSHOT_DIR / f"e2e_{name}.png")
    page.close()
    assert page.url == vision_base + path, f"{name}: unexpectedly redirected to {page.url}"
    assert not errors, f"{name}: {errors}"
