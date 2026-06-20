"""Tests for bank transaction ↔ invoice_file best-match logic (service.sync_match).

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
    BankTransaction,
    Customer,
    Invoice,
    InvoiceFile,
    Supplier,
    _InvoiceDirection,
    _PaymentStatus,
)
from invoice_core.service import _amount_candidates, _find_invoice_by_ref, _vendor_tokens, sync_match


@pytest.fixture
def mdb():
    """Fully isolated in-memory DB (sync_match commits, so no shared engine)."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


def _txn(**kw) -> BankTransaction:
    kw.setdefault("currency", "HUF")
    kw.setdefault("transaction_date", datetime(2026, 6, 1))
    kw.setdefault("bank", "wise")
    kw.setdefault("direction", "DEBIT")
    return BankTransaction(**kw)


# ── helper unit tests ──────────────────────────────────────────────────────────

class TestAmountCandidates:
    def test_eur_decimal_comma(self):
        t = _txn(transaction_id="x", amount=5434.98,
                 description="15,19 EUR értékű kártyahasználat ennél a kereskedőnél: Online (PARIS)")
        assert "15,19" in _amount_candidates(t)

    def test_huf_grouped_and_plain(self):
        t = _txn(transaction_id="x", amount=3400,
                 description="3 400,00 HUF értékű kártyahasználat")
        cands = _amount_candidates(t)
        assert "3400" in cands
        assert "3.400,00" in cands

    def test_decimal_comma_to_dot(self):
        # Scaleway invoices render the amount as "€3.25", txn description has "3,25"
        t = _txn(transaction_id="x", amount=1163.08, description="3,25 EUR értékű kártyahasználat")
        assert "3.25" in _amount_candidates(t)

    def test_fee_adjusted_net_amount(self):
        # Bank debited 94 624 HUF (of which 424 HUF is a fee); invoice shows 94 200 HUF
        t = _txn(transaction_id="x", amount=94624, fees=424,
                 description="Küldött utalás")
        cands = _amount_candidates(t)
        assert "94200" in cands
        assert "94.200" in cands
        assert "94.200,00" in cands


class TestVendorTokens:
    def test_brand_tokens_extracted(self):
        t = _txn(transaction_id="x", amount=1, counterparty_name="Scaleway PARIS")
        assert "scaleway" in _vendor_tokens(t)

    def test_own_company_and_cities_filtered(self):
        t = _txn(transaction_id="x", amount=1, counterparty_name="Google Workspace_graphtre Dublin")
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
    t_online = _txn(transaction_id="CARD-1", amount=5434.98, counterparty_name="Online PARIS",
                    transaction_date=datetime(2026, 6, 1),
                    description="15,19 EUR értékű kártyahasználat ennél a kereskedőnél: Online (PARIS)")
    t_scaleway = _txn(transaction_id="CARD-2", amount=1163.08, counterparty_name="Scaleway PARIS",
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
    t1 = _txn(transaction_id="CARD-A", amount=3400, counterparty_name="Simplep*Fizetes Budapest",
              transaction_date=datetime(2026, 5, 29),
              description="3 400,00 HUF értékű kártyahasználat ennél a kereskedőnél: Simplep*Fizetes (Budapest)")
    t2 = _txn(transaction_id="CARD-B", amount=3400, counterparty_name="Simplep*Fizetes Budapest",
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
    t = _txn(transaction_id="CARD-3", amount=5772.36, counterparty_name="Google Workspace_graphtre Dublin",
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
    t = _txn(transaction_id="TRANSFER-8", amount=127000, direction="CREDIT", currency="HUF",
             payment_reference="GRPHT-2026-11", counterparty_name="UNIOMEDIA KOMMUNIKÁCIÓS ÜGYNÖKSÉG",
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
    t = _txn(transaction_id="TRANSFER-8b", amount=127000, direction="CREDIT",
             payment_reference="GRPHT-2026-11",
             transaction_date=datetime(2026, 5, 21))
    mdb.add(t)
    mdb.flush()

    assert sync_match(mdb) == 1
    assert t.invoice_file_id == f.id


def test_payment_reference_company_prefix_stripped(mdb):
    # "Graphtrek 87/2026" is the bank transfer közlemény; the PDF only has "87/2026".
    # Full norm "graphtrek 87-2026" won't be a substring, but subtoken "87-2026" must match.
    f = InvoiceFile(
        filename="2026-06-04_0020_GRAPHTREK_szamla.pdf",
        words="87/2026 94200 fazekas ugyvedi iroda",
    )
    mdb.add(f)
    mdb.flush()
    t = _txn(
        transaction_id="TRANSFER-2173212738",
        amount=94624,
        fees=424,
        payment_reference="Graphtrek 87/2026",
        counterparty_name="Fazekas ugyvedi iroda",
        description="Utalás Fazekas ugyvedi iroda részére",
    )
    mdb.add(t)
    mdb.flush()

    assert sync_match(mdb) == 1
    assert t.invoice_file_id == f.id


def test_fee_adjusted_amount_matches_transfer(mdb):
    # Bank debited 94 624 HUF (fee 424 HUF); the PDF has 94 200 HUF.
    # "graphtrek" and "szamla" are stopwords, so the match must come via amount.
    f = InvoiceFile(
        filename="2026-06-04_0020_GRAPHTREK_szamla.pdf",
        words="94.200,00 94200 orzsem services kft",
    )
    mdb.add(f)
    mdb.flush()
    t = _txn(
        transaction_id="TRANSFER-2173212738",
        amount=94624,
        fees=424,
        counterparty_name="Őrszem Services Kft",
        transaction_date=datetime(2026, 6, 4),
        description="Küldött utalás Őrszem Services Kft. részére",
    )
    mdb.add(t)
    mdb.flush()

    assert sync_match(mdb) == 1
    assert t.invoice_file_id == f.id


def test_file_shared_backlinks_transaction_to_invoice(mdb):
    """Pre-existing file link on both sides triggers Phase 3 back-link."""
    supplier = Supplier(name="Teszt Szállító", tax_id="12345678-1-42")
    customer = Customer(name="Teszt Vevő", tax_id="87654321-2-13")
    pdf = InvoiceFile(filename="2026-06-05_0025_GRPHT-2026-15.pdf", words="2026-15 teszt")
    mdb.add_all([supplier, customer, pdf])
    mdb.flush()
    inv = Invoice(
        invoice_number="GRPHT-2026-15",
        supplier_id=supplier.id,
        customer_id=customer.id,
        payment_status=_PaymentStatus.UNPAID,
        direction=_InvoiceDirection.OUTBOUND,
        invoice_file_id=pdf.id,
    )
    mdb.add(inv)
    mdb.flush()
    # Transaction already linked to the same file (e.g. from a prior sync) but
    # not yet linked to the invoice.
    t = BankTransaction(
        transaction_id="TRANSFER-99",
        bank="wise",
        direction="DEBIT",
        amount=127000,
        currency="HUF",
        transaction_date=datetime(2026, 6, 5),
        invoice_file_id=pdf.id,
    )
    mdb.add(t)
    mdb.flush()

    sync_match(mdb)

    assert t.invoice_id == inv.id
    assert inv.payment_status == _PaymentStatus.PAID


def test_file_assigned_then_backlinked_in_same_call(mdb):
    """Phase 2 assigns the file; Phase 3 immediately links the invoice in the same sync_match call."""
    supplier = Supplier(name="Orzsem Services Kft", tax_id="11223344-1-01")
    customer = Customer(name="Graphtrek Kft", tax_id="99887766-2-02")
    pdf = InvoiceFile(
        filename="2026-06-04_0020_orzsem-services.pdf",
        words="94.200,00 94200 orzsem services kft",
    )
    mdb.add_all([supplier, customer, pdf])
    mdb.flush()
    inv = Invoice(
        invoice_number="ORZSEM-2026-42",
        supplier_id=supplier.id,
        customer_id=customer.id,
        payment_status=_PaymentStatus.UNPAID,
        direction=_InvoiceDirection.INBOUND,
        invoice_file_id=pdf.id,
    )
    mdb.add(inv)
    mdb.flush()
    # Transaction has no file link yet; Phase 2 will match it by amount + vendor.
    t = _txn(
        transaction_id="TRANSFER-ORZSEM",
        amount=94624,
        fees=424,
        counterparty_name="Őrszem Services Kft",
        transaction_date=datetime(2026, 6, 4),
        description="Küldött utalás Őrszem Services Kft. részére",
    )
    mdb.add(t)
    mdb.flush()

    sync_match(mdb)

    assert t.invoice_file_id == pdf.id    # Phase 2 matched the file
    assert t.invoice_id == inv.id         # Phase 3 back-linked the invoice
    assert inv.payment_status == _PaymentStatus.PAID


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
    t = _txn(transaction_id="TRANSFER-1", amount=71440, direction="DEBIT",
             payment_reference="2026-000064",
             description="Utalás Őrszem Services Kft. részére", invoice_id=inv.id)
    mdb.add(t)
    mdb.flush()

    assert sync_match(mdb) == 1
    assert t.invoice_file_id == pdf.id


def test_payment_reference_with_trailing_payer_name(mdb):
    # Erste payment_reference "KE26/42278 Graphtrek Kft" must resolve to invoice KE26/42278.
    # The full-reference LIKE "KE26%42278%Graphtrek%Kft" yields no candidates because
    # the invoice number doesn't contain "Graphtrek".  The subtoken path must kick in.
    supplier = Supplier(name="Swiss Medical Hungary Zrt", tax_id="12345678-1-42")
    customer = Customer(name="Graphtrek Kft", tax_id="87654321-2-13")
    mdb.add_all([supplier, customer])
    mdb.flush()
    inv = Invoice(
        invoice_number="KE26/42278",
        supplier_id=supplier.id,
        customer_id=customer.id,
        payment_status=_PaymentStatus.UNPAID,
        direction=_InvoiceDirection.INBOUND,
    )
    mdb.add(inv)
    mdb.flush()

    result = _find_invoice_by_ref(mdb, "KE26/42278 Graphtrek Kft")
    assert result is not None
    assert result.id == inv.id
