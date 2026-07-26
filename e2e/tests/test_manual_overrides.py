"""REQUIREMENTS acceptance criterion: a manually set invoice note, paid flag, PDF link, or
transaction link survives a subsequent sync unchanged.

Picks the first invoice returned by the list endpoint, applies all four manual overrides, runs
a sync stage, and asserts all four are exactly as left.
"""
import pytest


@pytest.fixture()
def sample_invoice_and_transaction(base_urls, api_session):
    core = base_urls["invoice_core"]
    invoices = api_session.get(f"{core}/api/v1/invoices", timeout=10).json()
    if not invoices:
        pytest.skip("no invoices in the database to test manual overrides against")
    invoice = invoices[0]

    transactions = api_session.get(f"{core}/api/v1/transactions", timeout=10).json()
    # Prefer a transaction not already linked to this invoice.
    txn = next(
        (t for t in transactions if t["id"] not in invoice.get("bank_transaction_db_ids", [])),
        None,
    )
    if txn is None:
        pytest.skip("no unlinked bank transaction available to test manual linking against")
    return invoice, txn


def test_manual_overrides_survive_sync(base_urls, api_session, sample_invoice_and_transaction):
    core = base_urls["invoice_core"]
    invoice, txn = sample_invoice_and_transaction
    invoice_id = invoice["id"]
    file_id = invoice["invoice_file_id"]

    note_text = "e2e manual override regression test"
    resp = api_session.patch(
        f"{core}/api/v1/invoices/{invoice_id}",
        json={
            "note": note_text,
            "payment_status": "PAID",
            "payment_status_locked": True,
        },
        timeout=10,
    )
    assert resp.status_code == 200, resp.text

    if file_id is not None:
        resp = api_session.put(
            f"{core}/api/v1/invoices/{invoice_id}/invoice-file",
            json={"invoice_file_id": file_id},
            timeout=10,
        )
        assert resp.status_code == 200, resp.text

    resp = api_session.put(
        f"{core}/api/v1/invoices/{invoice_id}/transactions/{txn['id']}", timeout=10
    )
    assert resp.status_code == 200, resp.text

    before = api_session.get(f"{core}/api/v1/invoices/{invoice_id}", timeout=10).json()
    assert before["note"] == note_text
    assert before["payment_status"] == "PAID"
    assert before["payment_status_locked"] is True
    if file_id is not None:
        assert before["invoice_file_id"] == file_id
        assert before["invoice_file_locked"] is True
    assert txn["id"] in [t["id"] for t in before["bank_transactions"]]

    # Re-run a sync stage that could plausibly touch this invoice's paid/link state.
    resp = api_session.post(
        f"{core}/api/v1/sync/bank",
        json={"start_date": "2026-06-01", "end_date": "2026-06-30"},
        timeout=60,
    )
    assert resp.status_code == 200, resp.text
    resp = api_session.post(
        f"{core}/api/v1/sync/match",
        json={"start_date": "2026-06-01", "end_date": "2026-06-30"},
        timeout=60,
    )
    assert resp.status_code == 200, resp.text

    after = api_session.get(f"{core}/api/v1/invoices/{invoice_id}", timeout=10).json()
    assert after["note"] == note_text, "note did not survive sync"
    assert after["payment_status"] == "PAID", "manually-set paid flag did not survive sync"
    assert after["payment_status_locked"] is True
    if file_id is not None:
        assert after["invoice_file_id"] == file_id, "manual PDF link did not survive sync"
        assert after["invoice_file_locked"] is True
    assert txn["id"] in [t["id"] for t in after["bank_transactions"]], (
        "manual bank transaction link did not survive sync"
    )
