"""Sablon-logika tesztek — hiányzó adat helyettesítők, üres lista állapotok.

Ezek a DEF-003 (dashboard "SZÁLLÍTÓ" oszlop literal `None`-t ír ki), DEF-005
(Vevők oldal 0 sor esetén ellentmondó lapozó-lábléc) és DEF-008 (dashboard
"SZÁLLÍTÓ" oszlop minden sornál "— nincs partner —"-t mutatott, holott a
valódi API payloadban a supplier_id/supplier_name párban populálva jött) hibák
javításait fedik le.
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
        "aud": "moneypenny",
    }
    token = pyjwt.encode(payload, private_pem, algorithm="RS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client


EMPTY_DASHBOARD_KPIS = {
    "total_invoices": 0,
    "linked_pdfs": 0,
    "unpaid_invoices": 0,
    "unpaid_amount": 0,
    "recent_bank_count": 0,
    "supplier_count": 0,
    "customer_count": 0,
}


def test_dashboard_unlinked_supplier_shows_placeholder_not_none(monkeypatch, client, auth_header):
    """DEF-003: an invoice row with no supplier at all must render the shared
    '— nincs partner —' placeholder, never the literal string 'None'.

    Fixture shape matches a real `GET /api/v1/dashboard` payload captured from
    a running invoice-core (2026-07-26): `RecentInvoiceRow` always serializes
    both the `supplier_id` and `supplier_name` keys (both `None` together when
    no supplier matched the invoice)."""
    dashboard_data = {
        "kpis": EMPTY_DASHBOARD_KPIS,
        "recent_invoices": [
            {
                "id": 1,
                "invoice_number": "INV-0001",
                "invoice_date": "2026-06-01",
                "supplier_id": None,
                "supplier_name": None,
                "amount_total": 1000,
                "payment_status": "UNPAID",
            }
        ],
        "recent_transactions": [],
        "top_suppliers": [],
        "top_customers": [],
        "monthly_finance": [],
    }
    monkeypatch.setattr(InvoiceCoreClient, "get_dashboard", lambda self: dashboard_data)

    response = client.get("/ui/", headers={**auth_header, "Accept": "text/html"})

    assert response.status_code == 200
    assert "— nincs partner —" in response.text
    # the literal Python None must never leak into the rendered cell
    assert ">None<" not in response.text


def test_dashboard_real_payload_shape_renders_supplier_link(monkeypatch, client, auth_header):
    """DEF-008 regression, fixture rebuilt from a real `GET /api/v1/dashboard`
    payload captured from a running invoice-core (2026-07-26, invoice
    GRPHT-2026-13 / supplier id 3 / "GRAPHTREK Kft."): the earlier DEF-008 test
    hand-mocked `supplier_name` present with `supplier_id` absent, a shape the
    real API has never actually sent (both keys are always populated together
    once `sync_nav`/`sync_pdf` matched a supplier) -- that mismatch is what let
    the DEF-008 bug (every row rendering the placeholder despite a real
    supplier existing) hide behind a green test. With the real shape, the name
    must render as a link to the supplier detail page."""
    dashboard_data = {
        "kpis": EMPTY_DASHBOARD_KPIS,
        "recent_invoices": [
            {
                "id": 2,
                "invoice_number": "GRPHT-2026-13",
                "invoice_date": "2026-06-01",
                "supplier_id": 3,
                "supplier_name": "GRAPHTREK Kft.",
                "amount_total": 127000.0,
                "payment_status": "UNPAID",
            }
        ],
        "recent_transactions": [],
        "top_suppliers": [],
        "top_customers": [],
        "monthly_finance": [],
    }
    monkeypatch.setattr(InvoiceCoreClient, "get_dashboard", lambda self: dashboard_data)

    response = client.get("/ui/", headers={**auth_header, "Accept": "text/html"})

    assert response.status_code == 200
    assert '<a href="/ui/suppliers/3">GRAPHTREK Kft.</a>' in response.text
    assert "— nincs partner —" not in response.text


def test_dashboard_supplier_name_without_id_still_renders_name(monkeypatch, client, auth_header):
    """Defensive/robustness case, not currently observed in the real API (see
    `test_dashboard_real_payload_shape_renders_supplier_link` above -- today
    `supplier_id` and `supplier_name` are always populated together): if
    `supplier_name` is ever present without a `supplier_id` (e.g. a partial or
    older payload shape), the DEF-003 fix must not hide that name behind the
    placeholder -- it must render the plain name, with no link since there is
    no id to link to."""
    dashboard_data = {
        "kpis": EMPTY_DASHBOARD_KPIS,
        "recent_invoices": [
            {
                "id": 2,
                "invoice_number": "GRPHT-2026-13",
                "invoice_date": "2026-06-01",
                "supplier_name": "GRAPHTREK Kft.",
                "amount_total": 127000.0,
                "payment_status": "UNPAID",
            }
        ],
        "recent_transactions": [],
        "top_suppliers": [],
        "top_customers": [],
        "monthly_finance": [],
    }
    monkeypatch.setattr(InvoiceCoreClient, "get_dashboard", lambda self: dashboard_data)

    response = client.get("/ui/", headers={**auth_header, "Accept": "text/html"})

    assert response.status_code == 200
    assert "GRAPHTREK Kft." in response.text
    assert "— nincs partner —" not in response.text
    # no supplier_id in the payload -> no detail link can be built
    assert '<a href="/ui/suppliers/' not in response.text


def test_customers_empty_state_has_no_placeholder_row(monkeypatch, client, auth_header):
    """DEF-005: with zero customers, the tbody must stay empty (no manual
    'Nincs találat' <tr>) so DataTables' own empty-state handles the info line
    instead of counting a fake data row."""
    monkeypatch.setattr(InvoiceCoreClient, "get_customers", lambda self: [])

    response = client.get("/ui/customers", headers={**auth_header, "Accept": "text/html"})

    assert response.status_code == 200
    # no manual fallback row baked into the server-rendered HTML
    assert "<td" not in response.text.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    # DataTable is configured with an explicit empty-table message, matching
    # the pattern already used by suppliers/invoices/files/bank tables
    assert 'emptyTable: "Nincs találat"' in response.text


def test_customers_nonempty_state_renders_rows(monkeypatch, client, auth_header):
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_customers",
        lambda self: [
            {
                "id": 7,
                "name": "Beta Zrt",
                "tax_id": "12345678-1-42",
                "invoice_count": 3,
                "unpaid_count": 0,
                "invoice_total": 10000,
                "bank_count": 2,
                "bank_total": 5000,
                "last_invoice_date": "2026-05-01",
            }
        ],
    )

    response = client.get("/ui/customers", headers={**auth_header, "Accept": "text/html"})

    assert response.status_code == 200
    assert "Beta Zrt" in response.text


def test_base_datatable_swap_cleanup_scoped_to_swap_target(monkeypatch, client, auth_header):
    """Bug: opening the bank-transactions detail offcanvas (an htmx swap
    scoped to '#tx-offcanvas-body') permanently broke DataTables Responsive's
    collapsed/expanded child rows on the unrelated, still-visible
    '#transaction-table' in the background.

    Root cause: base.html's global 'htmx:beforeSwap' cleanup handler (added
    to avoid leaking a stale DataTable instance when a table's own container
    gets swapped, e.g. controlling/timesheet's '#timesheet-content') looked
    at every 'table.dataTable' in the whole document and destroyed it,
    regardless of whether that table had anything to do with the swap that
    was about to happen. destroy() unbinds Responsive's window resize
    listener and strips its 'dtr-inline collapsed' classes permanently, since
    nothing re-initializes a table outside of its own page script running
    again on its own container swap.

    Fix: only destroy a table that is actually inside (or is) the swap's
    'evt.detail.target' — this test locks in that the handler receives the
    event and checks containment before destroying."""
    monkeypatch.setattr(
        InvoiceCoreClient,
        "get_dashboard",
        lambda self: {
            "kpis": EMPTY_DASHBOARD_KPIS,
            "recent_invoices": [],
            "recent_transactions": [],
            "top_suppliers": [],
            "top_customers": [],
            "monthly_finance": [],
        },
    )

    response = client.get("/ui/", headers={**auth_header, "Accept": "text/html"})

    assert response.status_code == 200
    body = response.text
    assert "_dataTableSwapCleanupBound" in body
    # the handler must read evt.detail.target ...
    assert "function (evt)" in body
    assert "var target = evt.detail.target;" in body
    # ... and only destroy a table that is the target or contained by it,
    # never an unconditional document-wide destroy of every DataTable.
    assert "(el === target || target.contains(el))" in body
