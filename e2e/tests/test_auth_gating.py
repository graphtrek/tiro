"""AUTH_ENABLED=true acceptance criterion.

- An unauthenticated API call to any protected backend route (other than /health) returns 401.
- An unauthenticated browser hitting a protected vision page is redirected to /login.
- attachment-downloader is the documented AUTH_ENABLED exception (always open, since it is only
  ever called by invoice-core's own sync pipeline, never by a browser holding a user token).
"""
import requests

PROTECTED_ENDPOINTS = [
    ("invoice_core", "/api/v1/dashboard"),
    ("invoice_core", "/api/v1/invoices"),
    ("bank", "/balance-statement/all"),
    ("nav_invoice", "/invoices"),
    ("uploader", "/api/v1/files"),
    ("auth", "/auth/me"),
]


def test_protected_endpoints_require_auth(base_urls):
    failures = []
    for service, path in PROTECTED_ENDPOINTS:
        url = base_urls[service] + path
        resp = requests.get(url, timeout=5)
        if resp.status_code != 401:
            failures.append(f"{service}{path}: expected 401, got {resp.status_code}")
    assert not failures, "\n".join(failures)


def test_attachment_downloader_auth_disabled_override(base_urls):
    """Documented exception: ATTACHMENT_DOWNLOADER_AUTH_ENABLED=false overrides the shared flag."""
    resp = requests.get(base_urls["attachment_downloader"] + "/api/v1/cache", timeout=5)
    assert resp.status_code == 200


def test_vision_browser_request_redirects_to_login(base_urls):
    """A real browser sends Accept: text/html and should get a 302 to /login?next=..., not JSON 401."""
    resp = requests.get(
        base_urls["vision"] + "/ui/invoices",
        headers={"Accept": "text/html,application/xhtml+xml"},
        allow_redirects=False,
        timeout=5,
    )
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("/login?next=")


def test_vision_public_pages_stay_public(base_urls):
    # /pitch is documented to redirect to / (still public, no auth involved).
    for path in ("/", "/login", "/health"):
        resp = requests.get(base_urls["vision"] + path, timeout=5, allow_redirects=False)
        assert resp.status_code == 200, f"{path}: expected 200, got {resp.status_code}"

    resp = requests.get(base_urls["vision"] + "/pitch", timeout=5, allow_redirects=False)
    assert resp.status_code in (200, 301, 302, 307, 308), (
        f"/pitch: expected a redirect or 200, got {resp.status_code}"
    )
    resp = requests.get(base_urls["vision"] + "/pitch", timeout=5, allow_redirects=True)
    assert resp.status_code == 200, f"/pitch (followed): expected 200, got {resp.status_code}"
