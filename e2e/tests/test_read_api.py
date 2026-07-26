"""invoice-core read API smoke tests: shape + timing (flag anything over ~1s)."""
import time

import pytest

SLOW_THRESHOLD_S = 1.0


def _timed_get(session, url, **kwargs):
    start = time.monotonic()
    resp = session.get(url, timeout=30, **kwargs)
    elapsed = time.monotonic() - start
    return resp, elapsed


def test_dashboard(base_urls, api_session):
    resp, elapsed = _timed_get(api_session, f"{base_urls['invoice_core']}/api/v1/dashboard")
    assert resp.status_code == 200, resp.text
    assert elapsed < SLOW_THRESHOLD_S, f"dashboard took {elapsed:.2f}s"
    body = resp.json()
    assert "kpis" in body and "recent_invoices" in body and "last_sync" in body


def test_invoices_list_and_filters(base_urls, api_session):
    core = base_urls["invoice_core"]
    resp, elapsed = _timed_get(api_session, f"{core}/api/v1/invoices")
    assert resp.status_code == 200
    assert elapsed < SLOW_THRESHOLD_S, f"invoices took {elapsed:.2f}s"
    assert isinstance(resp.json(), list)

    resp = api_session.get(f"{core}/api/v1/invoices", params={"has_pdf": "true"}, timeout=10)
    assert resp.status_code == 200
    assert all(inv["invoice_file_id"] is not None for inv in resp.json())

    resp = api_session.get(
        f"{core}/api/v1/invoices", params={"supplier_name": "nonexistent-xyz"}, timeout=10
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_invoice_files(base_urls, api_session):
    resp, elapsed = _timed_get(api_session, f"{base_urls['invoice_core']}/api/v1/invoice-files")
    assert resp.status_code == 200
    assert elapsed < SLOW_THRESHOLD_S, f"invoice-files took {elapsed:.2f}s"
    assert isinstance(resp.json(), list)


def test_partners(base_urls, api_session):
    core = base_urls["invoice_core"]
    resp = api_session.get(f"{core}/api/v1/partners/suppliers", timeout=10)
    assert resp.status_code == 200
    suppliers = resp.json()
    assert isinstance(suppliers, list)
    if suppliers:
        resp = api_session.get(
            f"{core}/api/v1/partners/suppliers/{suppliers[0]['id']}", timeout=10
        )
        assert resp.status_code == 200

    resp = api_session.get(f"{core}/api/v1/partners/customers", timeout=10)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_transactions_and_balances(base_urls, api_session):
    core = base_urls["invoice_core"]
    resp, elapsed = _timed_get(api_session, f"{core}/api/v1/transactions")
    assert resp.status_code == 200
    assert elapsed < SLOW_THRESHOLD_S, f"transactions took {elapsed:.2f}s"
    assert isinstance(resp.json(), list)

    resp = api_session.get(f"{core}/api/v1/transactions/balances", timeout=10)
    assert resp.status_code == 200
    for row in resp.json():
        assert {"bank", "balance", "currency"} <= row.keys()


def test_sync_logs(base_urls, api_session):
    resp, elapsed = _timed_get(api_session, f"{base_urls['invoice_core']}/api/v1/sync/logs")
    assert resp.status_code == 200
    assert elapsed < SLOW_THRESHOLD_S, f"sync/logs took {elapsed:.2f}s"
    assert isinstance(resp.json(), list)


def test_reports(base_urls, api_session):
    core = base_urls["invoice_core"]
    resp = api_session.get(f"{core}/api/v1/reports/tax", params={"month": "2026-06"}, timeout=10)
    assert resp.status_code == 200
    assert "grand_total" in resp.json()

    resp = api_session.get(f"{core}/api/v1/reports/dividend", timeout=10)
    assert resp.status_code == 200
    assert "net_dividend_with_szocho" in resp.json()


def test_users_list(base_urls, api_session):
    resp = api_session.get(f"{base_urls['invoice_core']}/api/v1/users", timeout=10)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

def test_invoice_detail_by_invoice_number_for_unlinked_supplier_customer(base_urls, api_session):
    """DEF-003 regression: GET /api/v1/invoices/{invoice_number} 500s (ResponseValidationError)
    for any invoice whose supplier_id/customer_id is still null (unlinked) — InvoiceOut declares
    those fields as required `int` instead of `int | None`. The sibling by-id route
    (/api/v1/invoices/{invoice_id:int}) is unaffected since it returns a plain dict, not the
    strict InvoiceOut response_model.
    """
    core = base_urls["invoice_core"]
    invoices = api_session.get(f"{core}/api/v1/invoices", timeout=10).json()
    unlinked = [inv for inv in invoices if inv["supplier_id"] is None or inv["customer_id"] is None]
    if not unlinked:
        pytest.skip("no invoice with an unlinked supplier/customer available to reproduce with")
    invoice_number = unlinked[0]["invoice_number"]

    resp = api_session.get(f"{core}/api/v1/invoices/{invoice_number}", timeout=10)
    assert resp.status_code == 200, (
        f"GET /api/v1/invoices/{invoice_number} returned {resp.status_code}: {resp.text[:300]}"
    )
