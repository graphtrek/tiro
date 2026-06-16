"""Tests for Wise transaction ↔ invoice_file best-match logic (service.sync_match).

Fixtures mirror the real DB rows: foreign card receipts in EUR (Online 15,19 vs
Scaleway €3.25), two identical Simplepay 3400 HUF charges against two receipts,
a Google Workspace charge with no receipt, and a transitive invoice→file link.
"""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.db import (
    Base,
    Customer,
    Invoice,
    InvoiceFile,
    Supplier,
    WiseTransaction,
    _InvoiceDirection,
    _PaymentStatus,
)
from invoice_core.service import _amount_candidates, _vendor_tokens, sync_match


@pytest.fixture
def mdb():
    """Fully isolated in-memory DB (sync_match commits, so no shared engine)."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


def _txn(**kw) -> WiseTransaction:
    kw.setdefault("currency", "HUF")
    kw.setdefault("transaction_date", datetime(2026, 6, 1))
    return WiseTransaction(**kw)


# ── helper unit tests ──────────────────────────────────────────────────────────

class TestAmountCandidates:
    def test_eur_decimal_comma(self):
        t = _txn(wise_transaction_id="x", amount=-5434.98,
                 description="15,19 EUR értékű kártyahasználat ennél a kereskedőnél: Online (PARIS)")
        assert "15,19" in _amount_candidates(t)

    def test_huf_grouped_and_plain(self):
        t = _txn(wise_transaction_id="x", amount=-3400,
                 description="3 400,00 HUF értékű kártyahasználat")
        cands = _amount_candidates(t)
        assert "3400" in cands
        assert "3.400,00" in cands

    def test_decimal_comma_to_dot(self):
        # Scaleway invoices render the amount as "€3.25", txn description has "3,25"
        t = _txn(wise_transaction_id="x", amount=-1163.08, description="3,25 EUR értékű kártyahasználat")
        assert "3.25" in _amount_candidates(t)


class TestVendorTokens:
    def test_brand_tokens_extracted(self):
        t = _txn(wise_transaction_id="x", amount=-1, merchant="Scaleway PARIS")
        assert "scaleway" in _vendor_tokens(t)

    def test_own_company_and_cities_filtered(self):
        t = _txn(wise_transaction_id="x", amount=-1, merchant="Google Workspace_graphtre Dublin")
        toks = _vendor_tokens(t)
        assert "graphtre" not in toks  # our own company never counts
        assert "dublin" not in toks    # city is noise
        assert "workspace" in toks


# ── sync_match integration tests ────────────────────────────────────────────────

def _seed_foreign_files(mdb) -> tuple[InvoiceFile, InvoiceFile]:
    online = InvoiceFile(
        filename="2026-06-01_0016_Online_invoice-5382739.pdf",
        words="5382739 15,19 euros france graphtrek scaleway sd-154664",
    )
    scaleway = InvoiceFile(
        filename="2026-06-02_0017_scaleway-invoice-2026-05.pdf",
        words="3222079 €3.25 €3.45 billing graphtrek scaleway categories",
    )
    mdb.add_all([online, scaleway])
    mdb.flush()
    return online, scaleway


def test_amount_disambiguates_online_vs_scaleway(mdb):
    online, scaleway = _seed_foreign_files(mdb)
    t_online = _txn(wise_transaction_id="CARD-1", amount=-5434.98, merchant="Online PARIS",
                    transaction_date=datetime(2026, 6, 1),
                    description="15,19 EUR értékű kártyahasználat ennél a kereskedőnél: Online (PARIS)")
    t_scaleway = _txn(wise_transaction_id="CARD-2", amount=-1163.08, merchant="Scaleway PARIS",
                      transaction_date=datetime(2026, 6, 1),
                      description="3,25 EUR értékű kártyahasználat ennél a kereskedőnél: Scaleway (PARIS)")
    mdb.add_all([t_online, t_scaleway])
    mdb.flush()

    assert sync_match(mdb) == 2
    assert t_online.invoice_file_id == online.id
    assert t_scaleway.invoice_file_id == scaleway.id


def test_two_identical_charges_get_distinct_files(mdb):
    f1 = InvoiceFile(filename="2026-05-29_0012_KC0126-01204.pdf",
                     words="3.400,00 3400 25956537-2-13 forras.net")
    f2 = InvoiceFile(filename="2026-05-29_0013_KC0126-01205.pdf",
                     words="3.400,00 3400 23118342-2-43 forras.net")
    mdb.add_all([f1, f2])
    mdb.flush()
    t1 = _txn(wise_transaction_id="CARD-A", amount=-3400, merchant="Simplep*Fizetes Budapest",
              transaction_date=datetime(2026, 5, 29),
              description="3 400,00 HUF értékű kártyahasználat ennél a kereskedőnél: Simplep*Fizetes (Budapest)")
    t2 = _txn(wise_transaction_id="CARD-B", amount=-3400, merchant="Simplep*Fizetes Budapest",
              transaction_date=datetime(2026, 5, 29),
              description="3 400,00 HUF értékű kártyahasználat ennél a kereskedőnél: Simplep*Fizetes (Budapest)")
    mdb.add_all([t1, t2])
    mdb.flush()

    assert sync_match(mdb) == 2
    assert t1.invoice_file_id is not None
    assert t2.invoice_file_id is not None
    assert {t1.invoice_file_id, t2.invoice_file_id} == {f1.id, f2.id}


def test_no_confident_match_stays_null(mdb):
    _seed_foreign_files(mdb)  # neither file mentions Google/Workspace nor 16,20
    t = _txn(wise_transaction_id="CARD-3", amount=-5772.36, merchant="Google Workspace_graphtre Dublin",
             transaction_date=datetime(2026, 6, 1),
             description="16,20 EUR értékű kártyahasználat ennél a kereskedőnél: Google Workspace_graphtre (Dublin)")
    mdb.add(t)
    mdb.flush()

    assert sync_match(mdb) == 0
    assert t.invoice_file_id is None


def test_reference_present_but_absent_stays_null(mdb):
    # Incoming transfer for invoice GRPHT-2026-11 (no PDF exists). A different
    # invoice's PDF happens to contain the same amount + counterparty name —
    # must NOT be matched on that coincidence.
    other = InvoiceFile(filename="2026-06-04_0022_GRPHT-2026-13.pdf",
                        words="127000 uniomedia 2026-13 budapest")
    mdb.add(other)
    mdb.flush()
    t = _txn(wise_transaction_id="TRANSFER-8", amount=127000, currency="HUF",
             payment_reference="GRPHT-2026-11", payer_name="UNIOMEDIA KOMMUNIKÁCIÓS ÜGYNÖKSÉG",
             transaction_date=datetime(2026, 5, 21),
             description="Beérkezett utalás ... GRPHT-2026-11 közleménnyel")
    mdb.add(t)
    mdb.flush()

    assert sync_match(mdb) == 0
    assert t.invoice_file_id is None


def test_reference_found_in_file_links_directly(mdb):
    f = InvoiceFile(filename="2026-06-04_0022_GRPHT-2026-11.pdf", words="127000 uniomedia 2026-11")
    mdb.add(f)
    mdb.flush()
    t = _txn(wise_transaction_id="TRANSFER-8b", amount=127000, payment_reference="GRPHT-2026-11",
             transaction_date=datetime(2026, 5, 21))
    mdb.add(t)
    mdb.flush()

    assert sync_match(mdb) == 1
    assert t.invoice_file_id == f.id


def test_transitive_shortcut_via_invoice(mdb):
    supplier = Supplier(name="Szállító", tax_id="11111111-1-11")
    customer = Customer(name="Vevő", tax_id="22222222-2-22")
    pdf = InvoiceFile(filename="2026-06-01_0014_2026-000064.pdf", words="2026-000064 billingo")
    mdb.add_all([supplier, customer, pdf])
    mdb.flush()
    inv = Invoice(invoice_number="2026-000064", supplier_id=supplier.id, customer_id=customer.id,
                  payment_status=_PaymentStatus.UNPAID, direction=_InvoiceDirection.INBOUND,
                  invoice_file_id=pdf.id)
    mdb.add(inv)
    mdb.flush()
    # transfer with no vendor/amount signal in the PDF — only the invoice link
    t = _txn(wise_transaction_id="TRANSFER-1", amount=-71440, payment_reference="2026-000064",
             description="Utalás Őrszem Services Kft. részére", invoice_id=inv.id)
    mdb.add(t)
    mdb.flush()

    assert sync_match(mdb) == 1
    assert t.invoice_file_id == pdf.id
