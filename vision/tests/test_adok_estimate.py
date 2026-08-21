"""Becsult adok tab -- savable per-month gross revenue overrides.

Covers the "Becsult adok table should be able to save" feature: the adok
page must seed each upcoming month's "Becsult bevetel" input from a saved
`TaxEstimateOverride` (via invoice-core's
`/api/v1/reports/tax-estimate/overrides`) rather than always resetting to the
hardcoded 2,500,000 Ft fallback, and the new `POST /ui/adok/estimate` route
must forward the edited values back to invoice-core and redirect (303,
redirect-after-POST) so a reload proves the round trip.
"""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import vision.auth as vision_auth
from vision.api.main import app
from vision.clients.invoice_core import InvoiceCoreClient
from vision.ui.utils import local_today


@pytest.fixture(scope="module")
def keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


@pytest.fixture(autouse=True)
def local_jwks(keypair, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    _, public_pem = keypair
    monkeypatch.setattr(vision_auth, "_get_signing_key", lambda token, url: public_pem)


@pytest.fixture
def auth_header(keypair) -> dict[str, str]:
    private_pem, _ = keypair
    now = int(time.time())
    payload = {
        "sub": "google-user-1",
        "email": "imre.tatai@graphtrek.co",
        "name": "Imre Tatai",
        "provider": "google",
        "typ": "access",
        "iat": now,
        "exp": now + 900,
        "iss": "auth-service",
        "aud": "tiro",
    }
    token = pyjwt.encode(payload, private_pem, algorithm="RS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client


def _month_keys():
    """Return (this_month_int, next_month_int, this_month_key, next_month_key)
    from the real current Budapest date, so the test doesn't depend on any
    fixed "today" -- adok_page filters "Becsult adok" to months >= today."""
    today = local_today()
    year, this_month = today.year, today.month
    next_month = this_month + 1 if this_month < 12 else 1
    next_year = year if this_month < 12 else year + 1
    this_key = f"{year:04d}-{this_month:02d}"
    next_key = f"{next_year:04d}-{next_month:02d}"
    return this_month, next_month, this_key, next_key


def _empty_tax_report(year):
    return {
        "year": year,
        "grand_total": 0,
        "gross_revenue": 0,
        "tax_labels": [],
        "totals_by_type": {},
        "monthly": [],
        "transactions": [],
    }


def _estimate_report(year, month_keys):
    return {
        "year": year,
        "tao_rate": 0.10,
        "hipa_rate": 0.02,
        "monthly": [
            {
                "month": mk,
                "is_projected": False,
                "revenue": 0.0,
                "gross_revenue": 0.0,
                "expenses": 0.0,
                "vat_payable": 0.0,
                "tao_tax": 0.0,
                "hipa_tax": 0.0,
                "total": 0.0,
            }
            for mk in month_keys
        ],
        "totals": {"month": "Osszesen"},
    }


def _mock_report_clients(monkeypatch, estimate_monthly_keys, overrides_months):
    monkeypatch.setattr(
        InvoiceCoreClient, "get_tax_report", lambda self, year=None: _empty_tax_report(year)
    )
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_tax_estimate_report",
        lambda self, year=None: _estimate_report(year, estimate_monthly_keys),
    )
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_tax_estimate_overrides",
        lambda self, year=None: {"year": year, "months": overrides_months},
    )


def test_adok_estimate_uses_saved_override_and_falls_back_to_default(
    monkeypatch, client, auth_header
):
    this_month, next_month, this_key, next_key = _month_keys()
    # only the next month has a saved override -- this month must fall back
    # to the hardcoded 2.5M default.
    _mock_report_clients(
        monkeypatch,
        [this_key, next_key],
        [{"month": next_month, "gross_revenue": 3_000_000.0}],
    )

    response = client.get("/ui/adok", headers={**auth_header, "Accept": "text/html"})

    assert response.status_code == 200
    assert this_month != next_month
    # fallback default for the month with no saved override
    assert 'value="2500000"' in response.text
    # saved override value wins for the overridden month
    assert 'value="3000000"' in response.text


def test_adok_estimate_post_forwards_payload_and_redirects(monkeypatch, client, auth_header):
    captured = {}

    def fake_save(self, year, months):
        captured["year"] = year
        captured["months"] = months
        return {"year": year, "months": months}

    monkeypatch.setattr(InvoiceCoreClient, "save_tax_estimate_overrides", fake_save)

    response = client.post(
        "/ui/adok/estimate",
        data={"year": 2026, "month": ["8", "9"], "gross_revenue": ["2600000", "3100000"]},
        headers=auth_header,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/ui/adok?year=2026&saved=1"
    assert captured["year"] == 2026
    assert captured["months"] == [
        {"month": 8, "gross_revenue": 2600000.0},
        {"month": 9, "gross_revenue": 3100000.0},
    ]


def test_adok_estimate_post_client_error_redirects_with_error(monkeypatch, client, auth_header):
    monkeypatch.setattr(
        InvoiceCoreClient,
        "save_tax_estimate_overrides",
        lambda self, year, months: {"error": "Nem sikerult menteni a becsult beveteleket"},
    )

    response = client.post(
        "/ui/adok/estimate",
        data={"year": 2026, "month": ["8"], "gross_revenue": ["2600000"]},
        headers=auth_header,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/ui/adok?year=2026&error=")
    assert "menteni" in response.headers["location"]


def test_adok_page_shows_success_banner(monkeypatch, client, auth_header):
    _this_month, _next_month, this_key, _next_key = _month_keys()
    _mock_report_clients(monkeypatch, [this_key], [])

    response = client.get("/ui/adok?saved=1", headers={**auth_header, "Accept": "text/html"})

    assert response.status_code == 200
    assert "alert-success" in response.text
    assert "Becsült bevételek mentve" in response.text


def test_adok_page_shows_error_banner(monkeypatch, client, auth_header):
    _this_month, _next_month, this_key, _next_key = _month_keys()
    _mock_report_clients(monkeypatch, [this_key], [])

    response = client.get(
        "/ui/adok?error=Nem+sikerult+menteni", headers={**auth_header, "Accept": "text/html"}
    )

    assert response.status_code == 200
    assert "alert-danger" in response.text
    assert "Nem sikerult menteni" in response.text


def test_adok_estimate_input_has_no_submit_blocking_step(monkeypatch, client, auth_header):
    """DEF-015 regression: a `step="10000"` constraint on the "Becsult bevetel"
    input made the browser silently refuse to submit the Mentes form for any
    non-round revenue figure (e.g. 1234567), with no banner and no request
    ever reaching the server. The input must not carry a step value that
    rejects arbitrary non-negative numbers."""
    _this_month, _next_month, this_key, _next_key = _month_keys()
    _mock_report_clients(monkeypatch, [this_key], [])

    response = client.get("/ui/adok", headers={**auth_header, "Accept": "text/html"})

    assert response.status_code == 200
    assert 'name="gross_revenue"' in response.text
    assert 'step="10000"' not in response.text
    assert 'step="any"' in response.text


def test_adok_estimate_overrides_call_failing_falls_back_to_default(
    monkeypatch, client, auth_header
):
    """If GET /api/v1/reports/tax-estimate/overrides fails (e.g. endpoint not
    up yet), the page must still render using the 2.5M fallback rather than
    erroring out."""
    _this_month, _next_month, this_key, _next_key = _month_keys()
    monkeypatch.setattr(
        InvoiceCoreClient, "get_tax_report", lambda self, year=None: _empty_tax_report(year)
    )
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_tax_estimate_report",
        lambda self, year=None: _estimate_report(year, [this_key]),
    )
    monkeypatch.setattr(InvoiceCoreClient, "get_tax_estimate_overrides", lambda self, year=None: {})

    response = client.get("/ui/adok", headers={**auth_header, "Accept": "text/html"})

    assert response.status_code == 200
    assert 'value="2500000"' in response.text
