"""Tests for bank transaction ↔ invoice_file best-match logic (service.sync_match).

Fixtures mirror the real DB rows: foreign card receipts in EUR (Online 15,19 vs
Scaleway €3.25), two identical Simplepay 3400 HUF charges against two receipts,
a Google Workspace charge with no receipt, and a transitive invoice→file link.
"""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sqlalchemy import insert as sa_insert

from invoice_core.db import (
    Base,
    BankTransaction,
    Customer,
    Invoice,
    InvoiceFile,
    Supplier,
    _InvoiceDirection,
    _PaymentStatus,
    invoice_bank_transaction,
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

    assert inv in t.invoices
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
    assert inv in t.invoices              # Phase 3 back-linked the invoice
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
             description="Utalás Őrszem Services Kft. részére")
    mdb.add(t)
    mdb.flush()
    inv.bank_transactions.append(t)

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


# ── Manual lock guard tests ───────────────────────────────────────────────────

def _make_sup_cust(mdb):
    sup = Supplier(name="TestSupplier", tax_id="12345678-1-00")
    cust = Customer(name="TestCustomer", tax_id="87654321-1-00")
    mdb.add_all([sup, cust])
    mdb.flush()
    return sup, cust


def test_locked_invoice_not_relinked(mdb):
    """sync_match must not overwrite invoice.invoice_file_id when invoice_file_locked=True."""
    sup, cust = _make_sup_cust(mdb)
    original_file = InvoiceFile(filename="original.pdf", words="original content")
    other_file = InvoiceFile(filename="2026-06-01_0001_GRPHT-2026-1.pdf", words="GRPHT-2026-1 graphtrek")
    mdb.add_all([original_file, other_file])
    mdb.flush()

    inv = Invoice(
        invoice_number="GRPHT-2026-1",
        supplier_id=sup.id,
        customer_id=cust.id,
        payment_status=_PaymentStatus.UNPAID,
        direction=_InvoiceDirection.INBOUND,
        invoice_file_id=original_file.id,
        invoice_file_locked=True,
    )
    mdb.add(inv)
    mdb.flush()

    sync_match(mdb)
    mdb.refresh(inv)
    assert inv.invoice_file_id == original_file.id  # must not change


def test_locked_txn_not_relinked(mdb):
    """sync_match must not overwrite txn.invoice_file_id when invoice_file_locked=True."""
    original_file = InvoiceFile(filename="original.pdf", words="original content")
    other_file = InvoiceFile(
        filename="2026-06-01_0001_Scaleway.pdf",
        words="scaleway 3.25 eur graphtrek billing",
    )
    mdb.add_all([original_file, other_file])
    mdb.flush()

    txn = _txn(
        transaction_id="LOCKED-1",
        amount=1163.08,
        counterparty_name="Scaleway PARIS",
        description="3,25 EUR értékű kártyahasználat",
        invoice_file_id=original_file.id,
        invoice_file_locked=True,
    )
    mdb.add(txn)
    mdb.flush()

    sync_match(mdb)
    mdb.refresh(txn)
    assert txn.invoice_file_id == original_file.id  # must not change


def test_locked_txn_supplier_customer_not_backfilled_on_phase3_backlink(mdb):
    """Phase 3 (back-link via shared file) must still link the invoice, but must
    not overwrite a locked supplier_id/customer_id on the transaction."""
    supplier = Supplier(name="Teszt Szállító", tax_id="12345678-1-42")
    customer = Customer(name="Teszt Vevő", tax_id="87654321-2-13")
    pdf = InvoiceFile(filename="2026-06-05_0025_GRPHT-2026-16.pdf", words="2026-16 teszt")
    mdb.add_all([supplier, customer, pdf])
    mdb.flush()
    inv = Invoice(
        invoice_number="GRPHT-2026-16",
        supplier_id=supplier.id,
        customer_id=customer.id,
        payment_status=_PaymentStatus.UNPAID,
        direction=_InvoiceDirection.OUTBOUND,
        invoice_file_id=pdf.id,
    )
    mdb.add(inv)
    mdb.flush()
    t = BankTransaction(
        transaction_id="TRANSFER-LOCKED-99",
        bank="wise",
        direction="DEBIT",
        amount=127000,
        currency="HUF",
        transaction_date=datetime(2026, 6, 5),
        invoice_file_id=pdf.id,
        supplier_locked=True,
        customer_locked=True,
    )
    mdb.add(t)
    mdb.flush()

    sync_match(mdb)

    assert inv in t.invoices               # back-link still happens
    assert t.supplier_id is None           # but locked fields are not backfilled
    assert t.customer_id is None


def test_locked_txn_supplier_not_overwritten_by_phase15_match(mdb):
    """Phase 1.5 (supplier-name + amount match) must still link the invoice,
    but must not overwrite a locked supplier_id/customer_id on the transaction."""
    supplier = Supplier(name="Orzsem Services Kft", tax_id="11223344-1-01")
    customer = Customer(name="Graphtrek Kft", tax_id="99887766-2-02")
    mdb.add_all([supplier, customer])
    mdb.flush()
    inv = Invoice(
        invoice_number="ORZSEM-2026-77",
        supplier_id=supplier.id,
        customer_id=customer.id,
        payment_status=_PaymentStatus.UNPAID,
        direction=_InvoiceDirection.INBOUND,
        invoice_date=datetime(2026, 6, 4).date(),
        amount_total=94624,
        currency="HUF",
    )
    mdb.add(inv)
    mdb.flush()
    t = _txn(
        transaction_id="TRANSFER-ORZSEM-LOCKED",
        amount=94624,
        counterparty_name="Őrszem Services Kft",
        transaction_date=datetime(2026, 6, 4),
        supplier_locked=True,
        customer_locked=True,
    )
    mdb.add(t)
    mdb.flush()

    sync_match(mdb)
    mdb.refresh(t)

    assert inv in t.invoices          # still matched to the invoice via supplier+amount
    assert t.supplier_id is None      # but the locked supplier/customer are not backfilled
    assert t.customer_id is None


def test_manual_m2m_survives_sync(mdb):
    """M2M row with manual=True must not be removed by sync_match."""
    sup, cust = _make_sup_cust(mdb)
    f = InvoiceFile(filename="manual.pdf", words="manual content")
    mdb.add(f)
    mdb.flush()

    inv = Invoice(
        invoice_number="MAN-2026-1",
        supplier_id=sup.id,
        customer_id=cust.id,
        payment_status=_PaymentStatus.UNPAID,
        direction=_InvoiceDirection.INBOUND,
        amount_total=10000,
        currency="HUF",
    )
    txn = _txn(transaction_id="MANUAL-TXN-1", amount=10000)
    mdb.add_all([inv, txn])
    mdb.flush()

    mdb.execute(sa_insert(invoice_bank_transaction).values(
        invoice_id=inv.id, bank_transaction_id=txn.id, manual=True,
    ))
    mdb.flush()

    sync_match(mdb)

    rows = mdb.execute(
        invoice_bank_transaction.select().where(
            invoice_bank_transaction.c.invoice_id == inv.id,
            invoice_bank_transaction.c.bank_transaction_id == txn.id,
        )
    ).all()
    assert len(rows) == 1  # manual row still present


def test_locked_txn_not_cleared_by_tax_guard(mdb, monkeypatch):
    """sync_bank's tax-account clearing must skip transactions with invoice_file_locked=True."""
    from invoice_core.bank_client import BankClient
    from invoice_core.config import Settings
    from invoice_core.service import sync_bank

    tax_account = "10032000-00290080-00000000"
    settings = Settings(
        db_url="sqlite:///:memory:",
        tax_accounts={tax_account: "NAV ÁFA"},
    )

    f = InvoiceFile(filename="locked.pdf", words="content")
    mdb.add(f)
    mdb.flush()

    txn = _txn(
        transaction_id="TAX-LOCKED-1",
        amount=5000,
        counterparty_account=tax_account,
        invoice_file_id=f.id,
        invoice_file_locked=True,
    )
    mdb.add(txn)
    mdb.commit()

    monkeypatch.setattr(BankClient, "get_transactions", lambda self: [])
    sync_bank("2026-06-01", "2026-06-30", mdb, settings)

    mdb.refresh(txn)
    assert txn.invoice_file_id == f.id  # still linked — the lock protected it
    assert txn.invoice_file_locked is True


def test_locked_txn_supplier_not_cleared_by_tax_guard(mdb, monkeypatch):
    """sync_bank's tax-account clearing clears the file/invoice link (unlocked),
    but must not null out a supplier_id the user explicitly locked."""
    from invoice_core.bank_client import BankClient
    from invoice_core.config import Settings
    from invoice_core.service import sync_bank

    tax_account = "10032000-00290080-00000000"
    settings = Settings(
        db_url="sqlite:///:memory:",
        tax_accounts={tax_account: "NAV ÁFA"},
    )

    supplier = Supplier(name="Szállító", tax_id="11111111-1-11")
    mdb.add(supplier)
    f = InvoiceFile(filename="reclassified.pdf", words="content")
    mdb.add(f)
    mdb.flush()

    txn = _txn(
        transaction_id="TAX-LOCKED-2",
        amount=5000,
        counterparty_account=tax_account,
        invoice_file_id=f.id,
        invoice_file_locked=False,
        supplier_id=supplier.id,
        supplier_locked=True,
    )
    mdb.add(txn)
    mdb.commit()

    monkeypatch.setattr(BankClient, "get_transactions", lambda self: [])
    sync_bank("2026-06-01", "2026-06-30", mdb, settings)

    mdb.refresh(txn)
    assert txn.invoice_file_id is None        # unlocked file link is cleared as before
    assert txn.supplier_id == supplier.id     # locked supplier survives the clear


def test_tax_account_clearing_recomputes_payment_status(mdb, monkeypatch):
    """sync_bank's tax-account clearing must recompute payment_status for invoices
    that lose their only linked transaction, not leave them stuck as PAID."""
    from invoice_core.bank_client import BankClient
    from invoice_core.config import Settings
    from invoice_core.service import sync_bank

    tax_account = "10032000-00290080-00000000"
    settings = Settings(
        db_url="sqlite:///:memory:",
        tax_accounts={tax_account: "NAV ÁFA"},
    )

    supplier = Supplier(name="Szállító", tax_id="11111111-1-11")
    customer = Customer(name="Vevő", tax_id="22222222-2-22")
    mdb.add_all([supplier, customer])
    mdb.flush()
    inv = Invoice(
        invoice_number="2026-000099", supplier_id=supplier.id, customer_id=customer.id,
        amount_total=5000, payment_status=_PaymentStatus.PAID,
        direction=_InvoiceDirection.INBOUND,
    )
    mdb.add(inv)
    mdb.flush()

    txn = _txn(
        transaction_id="TAX-1", amount=5000, counterparty_account=tax_account,
    )
    txn.invoices.append(inv)
    mdb.add(txn)
    mdb.commit()

    monkeypatch.setattr(BankClient, "get_transactions", lambda self: [])

    sync_bank("2026-06-01", "2026-06-30", mdb, settings)

    mdb.refresh(inv)
    assert inv.payment_status == _PaymentStatus.UNPAID
    assert inv.bank_transactions == []
