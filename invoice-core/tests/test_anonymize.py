"""Tests for the `anonymized: bool` JWT-claim-driven data masking.

Covers the pure primitives in `invoice_core.anonymize` (determinism, and
that the nested `SupplierDetail`-shaped payload scales every child amount
by the same factor as its parent partner), plus an end-to-end API test
against a real DB-backed `GET /api/v1/dashboard` for the three reachable
claim shapes:

- `role=read_write` -> real data (unaffected by this change).
- `role=read_only, anonymized=false` -> real data (the trusted
  `READONLY_EMAILS`/`READONLY_DOMAINS` tier -- this is the critical
  regression check: `role == "read_only"` alone must NOT trigger masking).
- `role=read_only, anonymized=true` -> masked data (the new open tier).

The end-to-end test overrides `require_auth` directly (same pattern as
`test_dashboard_recent_invoice_supplier_id.py` and the other API tests in
this suite) rather than round-tripping through a real JWKS/RS256 flow --
`test_auth_jwks.py` shows that's how JWT-claim-shaped tests are done in
this repo (no real JWT signing helper exists here); what matters for this
feature is that `request.state.user` carries the right claims, which is
exactly what `require_auth` sets after verifying a real token.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from invoice_core.anonymize import (
    _FAKE_PDF_PREVIEW_BASE64,
    anonymize,
    fake_amount,
    fake_identifier,
    fake_name,
    fake_person_name,
    fake_transaction_text,
    should_anonymize,
)
from invoice_core.api.main import app
from invoice_core.auth import require_auth
from invoice_core.db import (
    BankTransaction,
    Base,
    Invoice,
    Supplier,
    TaxEstimateOverride,
    User,
    VacationRequest,
    _InvoiceDirection,
    get_db,
)

# ── Primitive determinism ────────────────────────────────────────────────────


def test_fake_name_is_deterministic_and_differs_from_input():
    real = "GRAPHTREK Kft."
    first = fake_name(real)
    second = fake_name(real)
    assert first == second
    assert first != real
    assert first  # non-empty


def test_fake_name_none_and_empty_pass_through():
    assert fake_name(None) is None
    assert fake_name("") == ""


def test_fake_amount_is_deterministic_and_differs_from_input():
    key = "tax_id:12345678"
    first = fake_amount(1000.0, key)
    second = fake_amount(1000.0, key)
    assert first == second
    assert first != 1000.0


def test_fake_amount_scales_by_key_not_by_value():
    """Two different amounts under the SAME key must scale by the same ratio."""
    key = "tax_id:12345678"
    a = fake_amount(1000.0, key)
    b = fake_amount(2000.0, key)
    assert round(a / 1000.0, 6) == round(b / 2000.0, 6)


def test_fake_amount_none_and_zero_pass_through_unchanged():
    assert fake_amount(None, "some-key") is None
    assert fake_amount(0.0, "some-key") == 0.0


def test_fake_amount_small_nonzero_value_is_still_scaled():
    result = fake_amount(0.01, "some-key")
    assert result != 0.01
    assert result != 0.0


def test_fake_identifier_is_deterministic_and_differs_from_input():
    real = "12345678"
    first = fake_identifier(real, "tax_id")
    second = fake_identifier(real, "tax_id")
    assert first == second
    assert first != real
    assert len(first) == 8
    assert first.isdigit()


def test_fake_identifier_none_passes_through():
    assert fake_identifier(None, "tax_id") is None


def test_fake_identifier_email_looks_like_email():
    result = fake_identifier("real@example.com", "email")
    assert result != "real@example.com"
    assert result.endswith("@example.invalid")


# ── anonymize() nested scaling ───────────────────────────────────────────────


def test_anonymize_supplier_detail_scales_nested_invoices_by_same_factor():
    payload = {
        "id": 1,
        "name": "GRAPHTREK Kft.",
        "tax_id": "12345678",
        "address": "1234 Budapest, Fő utca 1.",
        "email": "info@graphtrek.hu",
        "phone": "+36301234567",
        "iban": "HU12345678901234567890123456",
        "bban": None,
        "bank_accounts": None,
        "known_names": "GRAPHTREK, GraphTrek Kft",
        "invoices": [
            {
                "id": 1,
                "invoice_number": "INV-1",
                "amount_total": 1000.0,
                "payment_status": "PAID",
            },
            {
                "id": 2,
                "invoice_number": "INV-2",
                "amount_total": 2500.0,
                "payment_status": "UNPAID",
            },
        ],
        "bank_transactions": [],
    }

    result = anonymize(payload)

    assert result["name"] != payload["name"]
    assert result["name"]  # non-empty, plausible pseudonym
    assert result["tax_id"] != payload["tax_id"]
    assert result["invoices"][0]["invoice_number"] != "INV-1"
    assert result["invoices"][1]["invoice_number"] != "INV-2"
    assert result["invoices"][0]["invoice_number"] != result["invoices"][1]["invoice_number"]
    assert result["invoices"][0]["payment_status"] == "PAID"

    ratio_1 = result["invoices"][0]["amount_total"] / payload["invoices"][0]["amount_total"]
    ratio_2 = result["invoices"][1]["amount_total"] / payload["invoices"][1]["amount_total"]
    assert round(ratio_1, 6) == round(ratio_2, 6)
    assert result["invoices"][0]["amount_total"] != payload["invoices"][0]["amount_total"]


def test_anonymize_leaves_ids_dates_and_operational_fields_untouched():
    payload = {
        "id": 42,
        "invoice_number": "INV-42",
        "payment_status": "PAID",
        "direction": "INBOUND",
        "currency": "HUF",
        "invoice_date": "2026-05-01",
    }
    result = anonymize(payload)
    untouched = {k: v for k, v in payload.items() if k != "invoice_number"}
    assert {k: result[k] for k in untouched} == untouched
    assert result["invoice_number"] != payload["invoice_number"]


def test_anonymize_invoice_number_is_deterministic_and_plausible():
    real = "AHUW261564234"
    result = fake_identifier(real, "invoice_number")
    assert result != real
    assert fake_identifier(real, "invoice_number") == result
    assert len(result) == 13
    assert result[:4].isalpha() and result[:4].isupper()
    assert result[4:].isdigit()


def test_anonymize_project_code_is_deterministic_and_plausible():
    real = "ACME-001"
    result = fake_identifier(real, "code")
    assert result != real
    assert fake_identifier(real, "code") == result
    assert "-" in result


def test_anonymize_code_and_project_code_alias_to_the_same_fake_value():
    """`Project.code` (key "code") and `TimesheetEntry.project_code` (key
    "project_code") hold the same real value on different pages/reports --
    they must mask to the identical fake code, not diverge by field name."""
    real = "ACME-001"
    assert fake_identifier(real, "code") == fake_identifier(real, "project_code")


def test_anonymize_invoice_number_aliases_match_linked_variant():
    real = "AHUW261564234"
    assert fake_identifier(real, "invoice_number") == fake_identifier(
        real, "linked_invoice_number"
    )


def test_anonymize_masks_project_and_timesheet_payload_fields():
    payload = {
        "id": 1,
        "code": "ACME-001",
        "customer_name": "Acme Kft.",
        "usage_hours": 12.5,
    }
    result = anonymize(payload)
    assert result["code"] != payload["code"]
    assert result["customer_name"] != payload["customer_name"]
    assert result["usage_hours"] == payload["usage_hours"]  # not requested, left alone

    entry_payload = {
        "id": 1,
        "project_id": 1,
        "project_code": "ACME-001",
        "customer_name": "Acme Kft.",
    }
    entry_result = anonymize(entry_payload)
    assert entry_result["project_code"] == result["code"]  # same real value -> same fake value


def test_anonymize_invoice_numbers_list_masked_consistently_with_singular():
    """The plural `invoice_numbers` list must mask each entry the same way
    a lone `invoice_number` field would, so cross-references (e.g. a
    transaction linked to the same invoice shown elsewhere) stay consistent."""
    payload = {
        "invoice_number": "INV-1",
        "invoice_numbers": ["INV-1", "INV-2"],
    }
    result = anonymize(payload)
    assert result["invoice_number"] == result["invoice_numbers"][0]
    assert result["invoice_numbers"][1] != "INV-2"


def test_anonymize_month_fallback_keeps_month_rows_consistent():
    """No partner in scope -> falls back to the row's own `month` field, so
    repeat views of the same monthly aggregate stay internally consistent."""
    row_a = {"month": "2026-05", "income": 1000.0, "expense": 400.0}
    row_b = {"month": "2026-05", "income": 1000.0, "expense": 400.0}

    result_a = anonymize(row_a)
    result_b = anonymize(row_b)

    assert result_a["income"] == result_b["income"]
    assert result_a["expense"] == result_b["expense"]
    assert result_a["income"] != row_a["income"]


def test_anonymize_known_names_list_and_string_variants():
    list_payload = {"known_names": ["Foo Kft.", "Bar Zrt."]}
    result = anonymize(list_payload)
    assert result["known_names"][0] != "Foo Kft."
    assert result["known_names"][1] != "Bar Zrt."
    assert len(result["known_names"]) == 2

    string_payload = {"known_names": "Foo Kft., Bar Zrt."}
    result2 = anonymize(string_payload)
    assert result2["known_names"] != "Foo Kft., Bar Zrt."
    assert "," in result2["known_names"]


def test_anonymize_handles_none_values():
    payload = {"name": None, "amount_total": None, "tax_id": None}
    result = anonymize(payload)
    assert result == {"name": None, "amount_total": None, "tax_id": None}


def test_anonymize_masks_dividend_and_tax_estimate_scalar_fields():
    """`DividendReport`/`TaxEstimateMonthRow` carry plural `expenses` plus
    per-tax scalar fields (vat_payable, tao_tax, hipa_tax, szja_tax,
    szocho_tax) that are distinct AMOUNT_KEYS entries from the dashboard's
    singular `expense` -- regression check that both are covered."""
    payload = {
        "month": "2026-05",
        "revenue": 10000.0,
        "expenses": 4000.0,
        "vat_payable": 270.0,
        "tao_tax": 900.0,
        "hipa_tax": 200.0,
        "szja_tax": 150.0,
        "szocho_tax": 130.0,
        "total": 1650.0,
    }
    result = anonymize(payload)
    keys = (
        "revenue",
        "expenses",
        "vat_payable",
        "tao_tax",
        "hipa_tax",
        "szja_tax",
        "szocho_tax",
        "total",
    )
    for key in keys:
        assert result[key] != payload[key], key
        assert result[key] is not None


def test_anonymize_masks_amount_dict_fields_by_arbitrary_label():
    """`TaxReport.totals_by_type` / `TaxMonthRow.totals` are dict[str, float]
    keyed by an arbitrary tax-type label rather than a recognized AMOUNT_KEYS
    name -- every value in the dict must still be masked, and consistently
    with the surrounding row's scale key."""
    payload = {
        "month": "2026-05",
        "gross_revenue": 5000.0,
        "totals": {"NAV ÁFA": 500.0, "NAV TAO": 300.0},
        "row_total": 800.0,
    }
    result = anonymize(payload)
    assert result["totals"]["NAV ÁFA"] != 500.0
    assert result["totals"]["NAV TAO"] != 300.0
    # Same scale key (the row's own "month" fallback) -> same ratio as gross_revenue.
    ratio_gross = result["gross_revenue"] / payload["gross_revenue"]
    ratio_vat = result["totals"]["NAV ÁFA"] / payload["totals"]["NAV ÁFA"]
    assert round(ratio_gross, 6) == round(ratio_vat, 6)

    top_level = {"totals_by_type": {"NAV ÁFA": 1200.0}}
    top_result = anonymize(top_level)
    assert top_result["totals_by_type"]["NAV ÁFA"] != 1200.0


# ── should_anonymize ──────────────────────────────────────────────────────────


class _FakeState:
    def __init__(self, user):
        self.user = user


class _FakeRequest:
    def __init__(self, user):
        self.state = _FakeState(user)


def test_should_anonymize_true_only_when_claim_is_literally_true():
    assert should_anonymize(_FakeRequest({"role": "read_only", "anonymized": True})) is True


def test_should_anonymize_false_for_trusted_readonly_tier():
    assert should_anonymize(_FakeRequest({"role": "read_only", "anonymized": False})) is False


def test_should_anonymize_false_when_claim_missing():
    assert should_anonymize(_FakeRequest({"role": "read_only"})) is False


def test_should_anonymize_false_when_no_user_on_request_state():
    class _EmptyState:
        pass

    class _NoUserRequest:
        state = _EmptyState()

    assert should_anonymize(_NoUserRequest()) is False


def test_should_anonymize_checks_claim_only_not_role():
    """`should_anonymize` is a pure claim check -- it does not itself gate on
    `role`. In practice `read_write` sessions never carry `anonymized: true`,
    but proving the function's actual decision boundary here (rather than
    baking in an assumption about what `auth` will always issue) is what
    catches a future regression if that boundary changes."""
    assert should_anonymize(_FakeRequest({"role": "read_write", "anonymized": True})) is True


# ── End-to-end API test ──────────────────────────────────────────────────────


@pytest.fixture
def client():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    session = Session()

    def _get_db():
        yield session

    app.dependency_overrides[get_db] = _get_db
    try:
        yield TestClient(app), session
    finally:
        app.dependency_overrides.clear()
        session.close()


def _override_auth_with_claims(claims: dict):
    async def _auth(request: Request):
        request.state.user = claims
        yield claims

    return _auth


def _seed_dashboard_data(session):
    supplier = Supplier(name="Teszt Beszállító Kft.", tax_id="12345678")
    session.add(supplier)
    session.flush()
    session.add(
        Invoice(
            invoice_number="INV-DASH-1",
            invoice_date=date(2026, 6, 1),
            supplier_id=supplier.id,
            amount_total=1000.0,
            direction=_InvoiceDirection.INBOUND,
        )
    )
    session.commit()
    return supplier


@pytest.mark.parametrize(
    "claims,expect_real",
    [
        ({"role": "read_write"}, True),
        ({"role": "read_only", "anonymized": False}, True),
        ({"role": "read_only", "anonymized": True}, False),
    ],
    ids=["read_write", "trusted_read_only_not_anonymized", "open_read_only_anonymized"],
)
def test_dashboard_top_suppliers_respect_anonymized_claim(client, claims, expect_real):
    tc, session = client
    supplier = _seed_dashboard_data(session)

    app.dependency_overrides[require_auth] = _override_auth_with_claims(claims)

    resp = tc.get("/api/v1/dashboard")
    assert resp.status_code == 200
    body = resp.json()

    top_suppliers = body["top_suppliers"]
    assert len(top_suppliers) == 1

    if expect_real:
        assert top_suppliers[0]["name"] == supplier.name
        assert top_suppliers[0]["total"] == 1000.0
    else:
        assert top_suppliers[0]["name"] != supplier.name
        assert top_suppliers[0]["name"]
        assert top_suppliers[0]["total"] != 1000.0


@pytest.mark.parametrize(
    "claims,expect_real",
    [
        ({"role": "read_write"}, True),
        ({"role": "read_only", "anonymized": False}, True),
        ({"role": "read_only", "anonymized": True}, False),
    ],
    ids=["read_write", "trusted_read_only_not_anonymized", "open_read_only_anonymized"],
)
def test_transaction_balances_respect_anonymized_claim(client, claims, expect_real):
    """GET /api/v1/transactions/balances -- the bank balance summary shown at
    the top of vision's /ui/transactions page -- was originally not wired
    into anonymization at all (a real gap: the balance is plain financial
    data, same category as the dashboard KPI amounts)."""
    tc, session = client
    session.add(
        BankTransaction(
            bank="Erste",
            transaction_id="TXN-BAL-1",
            amount=1.0,
            currency="HUF",
            direction="CREDIT",
            transaction_date=datetime(2026, 6, 1),
            balance=50000.0,
        )
    )
    session.commit()

    app.dependency_overrides[require_auth] = _override_auth_with_claims(claims)

    resp = tc.get("/api/v1/transactions/balances")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1

    if expect_real:
        assert body[0]["balance"] == 50000.0
    else:
        assert body[0]["balance"] != 50000.0
    assert body[0]["bank"] == "Erste"  # institution label is not masked


def test_anonymize_masks_transaction_fees_and_transaction_id():
    payload = {
        "id": 1,
        "transaction_id": "2026061012345",
        "bank": "Erste",
        "amount": 1000.0,
        "fees": 15.0,
        "counterparty_name": "Some Kft.",
    }
    result = anonymize(payload)
    assert result["transaction_id"] != payload["transaction_id"]
    assert result["fees"] != payload["fees"]
    assert result["bank"] == "Erste"


def test_anonymize_masks_transaction_detail_side_panel_fields():
    """Fields shown on the vision 'Bank tranzakció részletei' side panel
    (partials/transaction_detail.html) that weren't in the original key
    sets: counterparty_bank_code, card_last_four, and invoice_file_filename
    (which -- per attachment-downloader's `YYYY-MM-DD_NNNN_<sanitized>.pdf`
    naming -- usually embeds the real supplier name or invoice number in the
    <sanitized> segment)."""
    payload = {
        "counterparty_bank_code": "117",
        "card_last_four": "4242",
        "invoice_file_filename": "2026-06-01_0007_ACME_Invoice_INV-42.pdf",
    }
    result = anonymize(payload)
    assert result["counterparty_bank_code"] != "117"
    assert result["counterparty_bank_code"].isdigit()
    assert result["card_last_four"] != "4242"
    assert len(result["card_last_four"]) == 4 and result["card_last_four"].isdigit()

    fname = result["invoice_file_filename"]
    assert fname != payload["invoice_file_filename"]
    assert fname.startswith("2026-06-01_0007_")  # date/counter prefix preserved
    assert fname.endswith(".pdf")  # extension preserved
    assert "ACME" not in fname and "INV-42" not in fname


def test_anonymize_filename_and_invoice_file_filename_alias_consistently():
    """The bare `filename` key (invoice-files list) and `invoice_file_filename`
    (transaction/invoice detail) hold the same real value for the same file
    on different pages -- must mask identically."""
    real = "2026-06-01_0007_ACME_Invoice.pdf"
    assert fake_identifier(real, "filename") == fake_identifier(real, "invoice_file_filename")


def test_anonymize_filename_without_recognized_prefix_still_masked():
    result = fake_identifier("random-upload.pdf", "filename")
    assert result != "random-upload.pdf"
    assert result


def test_anonymize_masks_transaction_description_and_payment_reference():
    """`description`/`payment_reference` are free text and often spell out
    the real counterparty name or invoice number in plain narrative -- must
    be replaced outright (not left passed-through) once the enclosing dict
    looks like a bank-transaction row."""
    payload = {
        "id": 1,
        "transaction_id": "TXN-1",
        "bank": "Erste",
        "description": "Átutalás ACME Kft. részére, INV-42",
        "payment_reference": "INV-42/2026",
    }
    result = anonymize(payload)
    assert result["description"] != payload["description"]
    assert result["payment_reference"] != payload["payment_reference"]
    assert "ACME" not in result["description"]
    assert "INV-42" not in result["payment_reference"]


def test_anonymize_does_not_mask_unrelated_description_fields():
    """A `description` field with no `bank`/`transaction_id` sibling (e.g. a
    TimesheetEntryOut work-log note) must be left untouched -- the same key
    name is reused for a completely different, non-financial kind of text."""
    payload = {
        "id": 1,
        "project_code": "ACME-001",
        "description": "Kódolás és tesztelés a heti sprint keretében",
    }
    result = anonymize(payload)
    assert result["description"] == payload["description"]


def test_fake_transaction_text_is_deterministic():
    real = "Átutalás ACME Kft. részére"
    assert fake_transaction_text(real, "description") == fake_transaction_text(
        real, "description"
    )
    assert fake_transaction_text(real, "description") != real


def test_anonymize_masks_invoice_detail_page_shape():
    """GET /api/v1/invoices/{id}:int -- vision's /ui/invoices/{id} page --
    returns a nested InvoiceDetail dict: top-level supplier_tax_id/
    customer_tax_id, a NAV-snapshot `detail` dict with supplier_address/
    customer_address/supplier_tax_number/customer_tax_number/
    supplier_bank_account/customer_bank_account and gross/net/vat amounts,
    and a `lines` list with `line_description` ("Megnevezés") plus per-line
    amounts. All of these were unrecognized key names in the original
    AMOUNT_KEYS/IDENTIFIER_KEYS sets."""
    payload = {
        "id": 12,
        "supplier_id": 1,
        "supplier_name": "ACME Kft.",
        "supplier_tax_id": "12345678",
        "customer_id": 2,
        "customer_name": "Beta Zrt.",
        "customer_tax_id": "87654321",
        "amount_net": 1000.0,
        "amount_vat": 270.0,
        "amount_total": 1270.0,
        "detail": {
            "supplier_name": "ACME Kft.",
            "supplier_tax_number": "12345678",
            "supplier_address": "1111 Budapest, Fő utca 1.",
            "supplier_bank_account": "12345678-12345678-12345678",
            "customer_name": "Beta Zrt.",
            "customer_tax_number": "87654321",
            "customer_address": "2222 Debrecen, Kossuth utca 2.",
            "customer_bank_account": "87654321-87654321-87654321",
            "invoice_net_amount": 1000.0,
            "invoice_vat_amount": 270.0,
            "invoice_gross_amount": 1270.0,
        },
        "lines": [
            {
                "line_number": 1,
                "line_description": "Tanácsadási szolgáltatás ACME projekthez",
                "quantity": 1,
                "unit_price": 1000.0,
                "line_net_amount": 1000.0,
                "line_vat_amount": 270.0,
                "line_gross_amount": 1270.0,
            }
        ],
        "vat_summary": [
            {"vat_rate": 0.27, "vat_rate_net_amount": 1000.0, "vat_rate_vat_amount": 270.0}
        ],
    }
    result = anonymize(payload)

    assert result["supplier_tax_id"] != "12345678"
    assert result["customer_tax_id"] != "87654321"

    detail = result["detail"]
    assert detail["supplier_address"] != payload["detail"]["supplier_address"]
    assert detail["customer_address"] != payload["detail"]["customer_address"]
    assert detail["supplier_tax_number"] == result["supplier_tax_id"]  # alias consistency
    assert detail["customer_tax_number"] == result["customer_tax_id"]
    assert detail["supplier_bank_account"] != payload["detail"]["supplier_bank_account"]
    assert detail["customer_bank_account"] != payload["detail"]["customer_bank_account"]
    assert detail["invoice_net_amount"] != 1000.0
    assert detail["invoice_vat_amount"] != 270.0
    assert detail["invoice_gross_amount"] != 1270.0
    # Same invoice/supplier -> top-level amount_net and detail.invoice_net_amount
    # (same real value 1000.0) must scale by the identical factor.
    assert result["amount_net"] == detail["invoice_net_amount"]

    line = result["lines"][0]
    assert line["line_description"] != "Tanácsadási szolgáltatás ACME projekthez"
    assert "ACME" not in line["line_description"]
    assert line["unit_price"] != 1000.0
    assert line["line_net_amount"] != 1000.0
    assert line["line_net_amount"] == result["amount_net"]  # same entity, same scale factor
    assert line["line_vat_amount"] != 270.0
    assert line["line_gross_amount"] != 1270.0

    vat_row = result["vat_summary"][0]
    assert vat_row["vat_rate"] == 0.27  # a rate, not an amount -- left alone
    assert vat_row["vat_rate_net_amount"] != 1000.0
    assert vat_row["vat_rate_vat_amount"] != 270.0


def test_anonymize_supplier_address_and_detail_supplier_address_alias_consistently():
    real = "1111 Budapest, Fő utca 1."
    assert fake_identifier(real, "address") == fake_identifier(real, "supplier_address")
    assert fake_identifier(real, "address") == fake_identifier(real, "customer_address")


def test_anonymize_line_description_is_unconditional():
    """Unlike `description`, `line_description` has no unrelated-DTO
    collision risk, so it's masked with no sibling-key context check."""
    payload = {"line_description": "Tanácsadási díj ACME részére"}
    result = anonymize(payload)
    assert result["line_description"] != payload["line_description"]


def test_anonymize_invoice_file_row_shape():
    """GET /api/v1/invoice-files -- vision's /ui/invoice-files page. Covers
    the InvoiceFileRow fields not caught by the earlier `filename`/
    `linked_invoice_number`/`supplier_name`/`amount_total` fixes:
    `bank_transaction_id` (a real bank transaction reference under yet
    another field name), `bank_amount` (real money), `words` (the PDF's full
    extracted text -- no safe fake substitute, blanked outright), and
    `preview_base64` (a rendered image of the real PDF page -- replaced with
    a shared static fake preview image rather than left blank)."""
    payload = {
        "id": 1,
        "filename": "2026-06-01_0007_ACME_Invoice.pdf",
        "linked_invoice_number": "AHUW261564234",
        "supplier_name": "ACME Kft.",
        "amount_total": 1270.0,
        "bank_transaction_id": "TXN-BANK-1",
        "bank_amount": 1270.0,
        "bank_currency": "HUF",
        "words": "ACME Kft. Számla 1270 HUF Beta Zrt. részére",
        "preview_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB",
    }
    result = anonymize(payload)

    assert result["bank_transaction_id"] != "TXN-BANK-1"
    assert result["bank_amount"] != 1270.0
    assert result["amount_total"] == result["bank_amount"]  # same supplier scale factor
    assert result["words"] is None
    assert result["preview_base64"] == _FAKE_PDF_PREVIEW_BASE64
    assert result["preview_base64"] != payload["preview_base64"]


def test_anonymize_bank_transaction_id_aliases_with_transaction_id():
    real = "TXN-BANK-1"
    assert fake_identifier(real, "transaction_id") == fake_identifier(real, "bank_transaction_id")


def test_anonymize_redact_keys_leave_none_as_none():
    payload = {"words": None, "preview_base64": None}
    result = anonymize(payload)
    assert result == {"words": None, "preview_base64": None}


def test_anonymize_fake_preview_used_for_both_field_name_variants():
    """`preview_base64` (invoice-files list) and `invoice_file_preview_base64`
    (invoices list, transactions list) are the same real image under two
    different field names -- both get the identical shared fake preview."""
    payload = {"preview_base64": "real-bytes-1", "invoice_file_preview_base64": "real-bytes-2"}
    result = anonymize(payload)
    assert result["preview_base64"] == _FAKE_PDF_PREVIEW_BASE64
    assert result["invoice_file_preview_base64"] == _FAKE_PDF_PREVIEW_BASE64


def test_anonymize_masks_invoice_bank_transaction_ids_list():
    """`bank_transaction_ids` (plural, on InvoiceRow) is the list-valued
    counterpart of `bank_transaction_id` -- same real bank references, must
    mask consistently with the singular field."""
    payload = {
        "bank_transaction_id": "TXN-1",
        "bank_transaction_ids": ["TXN-1", "TXN-2"],
    }
    result = anonymize(payload)
    assert result["bank_transaction_id"] == result["bank_transaction_ids"][0]
    assert result["bank_transaction_ids"][1] != "TXN-2"


def test_anonymize_masks_timesheet_user_name():
    """`user_name` ("Felhasználó" on /ui/controlling/timesheet) --
    TimesheetEntryOut.user_name and report_service.DetailRow.user_name both
    funnel through this same key."""
    payload = {
        "id": 1,
        "user_id": 1,
        "user_name": "Tatai Imre",
        "project_code": "ACME-001",
        "customer_name": "Acme Kft.",
        "hours": 4.0,
    }
    result = anonymize(payload)
    assert result["user_name"] != "Tatai Imre"
    assert result["user_name"]
    # Reads as a person's name (given+family), not a fake company name.
    assert not any(suffix in result["user_name"] for suffix in ("Kft.", "Zrt.", "Bt.", "Nyrt."))
    assert len(result["user_name"].split()) == 2
    assert result["customer_name"] != "Acme Kft."  # still a company-style fake
    assert result["hours"] == 4.0  # not requested, left alone


def test_fake_person_name_is_deterministic_and_distinct_from_company_name():
    real = "Tatai Imre"
    first = fake_person_name(real)
    second = fake_person_name(real)
    assert first == second
    assert first != real
    assert not any(suffix in first for suffix in ("Kft.", "Zrt.", "Bt.", "Nyrt."))
    assert fake_person_name(real) != fake_name(real)


def test_fake_person_name_none_and_empty_pass_through():
    assert fake_person_name(None) is None
    assert fake_person_name("") == ""


def test_anonymize_masks_timesheet_participants():
    """`participants` ("Résztvevők") is a comma-separated list of real
    person names -- masked per-name with `fake_person_name`, same as
    `known_names` is per-name with `fake_name`."""
    payload = {"participants": "Kozma Zoltán, Erős Péter"}
    result = anonymize(payload)
    assert result["participants"] != payload["participants"]
    assert "Kozma Zoltán" not in result["participants"]
    assert "Erős Péter" not in result["participants"]
    assert "," in result["participants"]
    parts = [p.strip() for p in result["participants"].split(",")]
    assert len(parts) == 2
    assert all(len(p.split()) == 2 for p in parts)  # each reads as a person name


def test_anonymize_participants_none_and_empty_pass_through():
    assert anonymize({"participants": None})["participants"] is None
    assert anonymize({"participants": ""})["participants"] == ""


def test_anonymize_masks_timesheet_description_when_row_has_hours():
    """`description` on a timesheet row (has an `hours` sibling key) is now
    also masked -- distinct fake generator from the bank-transaction
    `description` case, and still correctly left alone for rows that are
    neither (e.g. an activity type's own description, no `hours`/`bank`/
    `transaction_id` sibling)."""
    payload = {
        "id": 1,
        "user_name": "Tatai Imre",
        "hours": 4.0,
        "description": "Ügyfél projekt fejlesztése ACME részére",
    }
    result = anonymize(payload)
    assert result["description"] != payload["description"]
    assert "ACME" not in result["description"]


def test_fake_transaction_text_work_description_differs_from_bank_description():
    real = "Ügyfél projekt fejlesztése ACME részére"
    work = fake_transaction_text(real, "work_description")
    bank = fake_transaction_text(real, "description")
    assert work != real
    assert work != bank  # different phrase banks for different contexts


def test_anonymize_masks_project_owner_name_as_a_person():
    """`owner_name` ("Project Gazda" on /ui/controlling/projects) is the
    project owner's real name -- masked as a person name, same as
    `user_name`, not a fake company name."""
    payload = {
        "id": 1,
        "code": "ACME-001",
        "customer_name": "Acme Kft.",
        "owner_name": "Tatai Imre",
    }
    result = anonymize(payload)
    assert result["owner_name"] != "Tatai Imre"
    assert not any(suffix in result["owner_name"] for suffix in ("Kft.", "Zrt.", "Bt.", "Nyrt."))
    assert result["owner_name"] == fake_person_name("Tatai Imre")


def test_anonymize_masks_project_short_name():
    """`short_name` ("Azonosító / rövid név") is the raw abbreviation
    `code` is composed from (project_service._compose_code) -- both fields
    are returned on ProjectOut, so masking `code` alone still left the raw
    short_name leaking in the same payload."""
    payload = {"id": 1, "short_name": "FVM", "code": "FVM-001"}
    result = anonymize(payload)
    assert result["short_name"] != "FVM"
    assert result["short_name"]
    assert result["code"] != "FVM-001"


def test_fake_identifier_short_name_is_deterministic_and_distinct_from_code():
    real = "FVM"
    first = fake_identifier(real, "short_name")
    second = fake_identifier(real, "short_name")
    assert first == second
    assert first != real
    assert first != fake_identifier(real, "code")


def test_anonymize_masks_supplier_known_bank_accounts():
    """`bank_accounts` ("Ismert bankszámlák") is a comma-separated history
    of every bban ever seen for this partner -- masked per-account like
    `known_names`/`participants`, not caught by the bare `bban` key (which
    only covers the partner's single *current* account)."""
    payload = {"bank_accounts": "11111111-22222222-33333333,44444444-55555555-66666666"}
    result = anonymize(payload)
    assert result["bank_accounts"] != payload["bank_accounts"]
    accounts = result["bank_accounts"].split(",")
    assert len(accounts) == 2
    assert "11111111-22222222-33333333" not in result["bank_accounts"]
    assert "44444444-55555555-66666666" not in result["bank_accounts"]


def test_anonymize_bank_accounts_none_and_empty_pass_through():
    assert anonymize({"bank_accounts": None})["bank_accounts"] is None
    assert anonymize({"bank_accounts": ""})["bank_accounts"] == ""


def test_anonymize_bank_accounts_entry_matches_bban_masking():
    """A single account in `bank_accounts` masks to the same fake value a
    bare `bban` field with that same real value would."""
    real = "11111111-22222222-33333333"
    assert anonymize({"bank_accounts": real})["bank_accounts"] == fake_identifier(real, "bban")


# ── Full-sweep findings: note masking, bank_txn_external_id alias ───────────


def test_anonymize_masks_note_on_transaction_row():
    payload = {"id": 1, "bank": "Erste", "note": "ACME Kft. részére, INV-42"}
    result = anonymize(payload)
    assert result["note"] != payload["note"]
    assert "ACME" not in result["note"]


def test_anonymize_masks_note_on_invoice_row():
    payload = {"id": 1, "invoice_number": "INV-42", "note": "Jóváhagyta Nagy János"}
    result = anonymize(payload)
    assert result["note"] != payload["note"]
    assert "Nagy János" not in result["note"]


def test_anonymize_masks_note_on_vacation_row_with_dedicated_phrase_bank():
    payload = {
        "id": 1,
        "user_name": "Tatai Imre",
        "start_date": "2026-07-01",
        "end_date": "2026-07-05",
        "note": "Nyaralás a családdal",
    }
    result = anonymize(payload)
    assert result["note"] != payload["note"]
    assert result["user_name"] != "Tatai Imre"


def test_anonymize_does_not_mask_note_with_no_recognized_context():
    """A `note` with none of the transaction/invoice/vacation sibling
    signals is left untouched -- safe default rather than guessing."""
    payload = {"id": 1, "code": "ACME-001", "note": "Belső feljegyzés"}
    result = anonymize(payload)
    assert result["note"] == payload["note"]


def test_anonymize_bank_txn_external_id_aliases_with_transaction_id():
    real = "TXN-EXT-1"
    assert fake_identifier(real, "transaction_id") == fake_identifier(real, "bank_txn_external_id")


# ── Endpoint wiring found missing in the full sweep ──────────────────────────


def test_fizetes_kalkulator_respects_anonymized_claim(client):
    """GET /api/v1/fizetes-kalkulator was not wired into anonymization at
    all -- real net_wage/revenue defaults were always returned as-is."""
    tc, _session = client
    app.dependency_overrides[require_auth] = _override_auth_with_claims(
        {"role": "read_only", "anonymized": True}
    )
    resp = tc.get("/api/v1/fizetes-kalkulator")
    assert resp.status_code == 200
    body = resp.json()
    assert body["net_wage"] != 1_000_000.0  # DEFAULT_NET_WAGE, masked
    assert body["revenue_touched"] is False  # non-amount field passes through


def test_vacation_requests_respect_anonymized_claim(client):
    """GET /api/v1/vacation-requests was not wired into anonymization at
    all -- real employee names and notes were always returned as-is."""
    tc, session = client
    user = User(provider="google", sub="u1", email="imre@example.com", name="Tatai Imre")
    session.add(user)
    session.flush()
    session.add(
        VacationRequest(
            user_id=user.id,
            kind="vacation",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 5),
            note="Nyaralás",
        )
    )
    session.commit()

    app.dependency_overrides[require_auth] = _override_auth_with_claims(
        {"role": "read_only", "anonymized": True}
    )
    resp = tc.get("/api/v1/vacation-requests")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["user_name"] != "Tatai Imre"
    assert body[0]["note"] != "Nyaralás"


def test_supplier_summary_respects_anonymized_claim(client):
    """GET /api/v1/partners/suppliers/summary was not wired into
    anonymization at all -- real aggregate invoice/bank totals across all
    suppliers were always returned as-is."""
    tc, session = client
    supplier = Supplier(name="ACME Kft.", tax_id="12345678")
    session.add(supplier)
    session.flush()
    session.add(
        Invoice(
            invoice_number="INV-SUM-1",
            invoice_date=date(2026, 6, 1),
            supplier_id=supplier.id,
            amount_total=5000.0,
            currency="HUF",
            direction=_InvoiceDirection.INBOUND,
        )
    )
    session.commit()

    app.dependency_overrides[require_auth] = _override_auth_with_claims(
        {"role": "read_only", "anonymized": True}
    )
    resp = tc.get("/api/v1/partners/suppliers/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["invoice_totals"]) == 1
    assert body["invoice_totals"][0]["total"] != 5000.0


def test_tax_estimate_overrides_respect_anonymized_claim(client):
    """GET /api/v1/reports/tax-estimate/overrides was not wired into
    anonymization at all -- real user-entered revenue overrides were always
    returned as-is."""
    tc, session = client
    session.add(TaxEstimateOverride(year=2026, month=6, gross_revenue=750_000.0))
    session.commit()

    app.dependency_overrides[require_auth] = _override_auth_with_claims(
        {"role": "read_only", "anonymized": True}
    )
    resp = tc.get("/api/v1/reports/tax-estimate/overrides", params={"year": 2026})
    assert resp.status_code == 200
    body = resp.json()
    assert body["months"][0]["gross_revenue"] != 750_000.0
