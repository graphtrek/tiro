"""Tests for tax_service.get_tax_estimate — monthly tax projection."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.db import Base, Invoice, InvoiceVatSummary, _InvoiceDirection
from invoice_core.services import tax_service


@pytest.fixture
def db():
    """Fully isolated in-memory DB (create/commit per test, no shared engine) —
    the tests here commit invoices directly, so a session-scoped shared engine
    (like conftest's) would leak data across tests within this file."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    # `get_tax_estimate` calls the `timeutil.today()` imported into this module
    # (UTC-aware), not `date.today()` — pin that seam so month-based projection
    # logic is deterministic in tests.
    monkeypatch.setattr(tax_service, "today", lambda: date(2026, 7, 15))


def _invoice(db, number, invoice_date, direction, amount_net, vat_amount=None, vat_rate=0.27):
    inv = Invoice(
        invoice_number=number,
        invoice_date=invoice_date,
        direction=direction,
        amount_net=amount_net,
        amount_vat=vat_amount,
        amount_total=(amount_net + vat_amount) if vat_amount is not None else amount_net,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    if vat_amount is not None:
        db.add(
            InvoiceVatSummary(
                invoice_id=inv.id,
                vat_rate=vat_rate,
                vat_rate_net_amount=amount_net,
                vat_rate_vat_amount=vat_amount,
            )
        )
        db.commit()
    return inv


def test_past_year_has_all_twelve_months_none_projected(db):
    _invoice(db, "OUT-2025-1", date(2025, 3, 10), _InvoiceDirection.OUTBOUND, 1000.0, 270.0)

    report = tax_service.get_tax_estimate(db, 2025)

    assert report.year == 2025
    assert [row.month for row in report.monthly] == [f"2025-{m:02d}" for m in range(1, 13)]
    assert all(not row.is_projected for row in report.monthly)

    march = next(row for row in report.monthly if row.month == "2025-03")
    assert march.revenue == 1000.0
    assert march.vat_payable == 270.0


def test_current_year_projects_remaining_months_from_trailing_average(db):
    _invoice(db, "OUT-2026-1", date(2026, 1, 10), _InvoiceDirection.OUTBOUND, 1000.0, 270.0)
    _invoice(db, "IN-2026-1", date(2026, 1, 15), _InvoiceDirection.INBOUND, 200.0, 54.0)
    _invoice(db, "OUT-2026-2", date(2026, 2, 10), _InvoiceDirection.OUTBOUND, 2000.0, 540.0)

    report = tax_service.get_tax_estimate(
        db, 2026, tao_rate=0.10, hipa_rate=0.02, szja_rate=0.15, szocho_rate=0.13
    )

    assert [row.month for row in report.monthly] == [f"2026-{m:02d}" for m in range(1, 13)]

    # Months 1-7 (through "today"'s month) are real, incl. zero months w/ no invoices.
    real = report.monthly[:7]
    assert all(not row.is_projected for row in real)
    march = next(row for row in real if row.month == "2026-03")
    assert march.revenue == 0.0 and march.expenses == 0.0 and march.total == 0.0

    jan = report.monthly[0]
    assert jan.revenue == 1000.0
    assert jan.gross_revenue == 1270.0
    assert jan.expenses == 200.0
    assert jan.vat_payable == 270.0 - 54.0

    # Months 8-12 are projected from the trailing average of the two nonzero
    # active months (Jan revenue=1000/expenses=200, Feb revenue=2000/expenses=0).
    projected = report.monthly[7:]
    assert len(projected) == 5
    assert all(row.is_projected for row in projected)
    expected_avg_revenue = (1000.0 + 2000.0) / 2
    expected_avg_gross_revenue = (1270.0 + 2540.0) / 2
    expected_avg_expenses = (200.0 + 0.0) / 2
    for row in projected:
        assert row.revenue == pytest.approx(expected_avg_revenue)
        assert row.gross_revenue == pytest.approx(expected_avg_gross_revenue)
        assert row.expenses == pytest.approx(expected_avg_expenses)

    assert report.totals.total == pytest.approx(sum(row.total for row in report.monthly))


def test_current_year_with_no_invoices_has_zero_projection_no_div_by_zero(db):
    report = tax_service.get_tax_estimate(db, 2026)

    assert len(report.monthly) == 12
    projected = [row for row in report.monthly if row.is_projected]
    assert len(projected) == 5
    assert all(row.revenue == 0.0 and row.total == 0.0 for row in projected)
    assert report.totals.total == 0.0


def test_override_substitutes_revenue_inputs_for_projected_month(db):
    # Real Jan data feeds the trailing average used for non-overridden
    # projected months (Aug-Dec, "today" pinned to 2026-07-15).
    _invoice(db, "OUT-2026-1", date(2026, 1, 10), _InvoiceDirection.OUTBOUND, 1000.0, 270.0)

    tax_service.save_estimate_overrides(db, 2026, {9: 3_000_000.0})

    report = tax_service.get_tax_estimate(db, 2026)

    sept = next(row for row in report.monthly if row.month == "2026-09")
    assert sept.is_override is True
    assert sept.is_projected is True
    assert sept.gross_revenue == 3_000_000.0
    expected_net = 3_000_000.0 / 1.27
    assert sept.revenue == pytest.approx(expected_net)
    assert sept.expenses == 0.0
    assert sept.vat_payable == pytest.approx(3_000_000.0 - expected_net)
    # tao/hipa/szja/szocho follow the standard _tax_row formula from the
    # substituted inputs -- assert they were actually computed, not zeroed.
    assert sept.tao_tax > 0.0
    assert sept.hipa_tax > 0.0

    # A non-overridden projected month keeps exactly today's behavior: the
    # trailing average of real (non-override) active months only.
    aug = next(row for row in report.monthly if row.month == "2026-08")
    assert aug.is_override is False
    assert aug.revenue == pytest.approx(1000.0)


def test_override_substitutes_revenue_inputs_for_elapsed_month(db):
    _invoice(db, "OUT-2026-3", date(2026, 3, 10), _InvoiceDirection.OUTBOUND, 5000.0, 1350.0)

    tax_service.save_estimate_overrides(db, 2026, {3: 1_000_000.0})

    report = tax_service.get_tax_estimate(db, 2026)

    march = next(row for row in report.monthly if row.month == "2026-03")
    assert march.is_override is True
    assert march.is_projected is False
    assert march.gross_revenue == 1_000_000.0
    expected_net = 1_000_000.0 / 1.27
    assert march.revenue == pytest.approx(expected_net)
    assert march.vat_payable == pytest.approx(1_000_000.0 - expected_net)

    # An unrelated real month is unaffected.
    jan = next(row for row in report.monthly if row.month == "2026-01")
    assert jan.is_override is False
    assert jan.revenue == 0.0


def test_get_estimate_overrides_empty_when_none_saved(db):
    assert tax_service.get_estimate_overrides(db, 2026) == {}


def test_save_estimate_overrides_round_trips(db):
    saved = tax_service.save_estimate_overrides(db, 2026, {8: 2_500_000.0, 9: 3_000_000.0})
    assert saved == {8: 2_500_000.0, 9: 3_000_000.0}
    assert tax_service.get_estimate_overrides(db, 2026) == {8: 2_500_000.0, 9: 3_000_000.0}


def test_save_estimate_overrides_upserts_without_duplicating(db):
    tax_service.save_estimate_overrides(db, 2026, {8: 2_500_000.0})
    saved = tax_service.save_estimate_overrides(db, 2026, {8: 2_700_000.0})

    assert saved == {8: 2_700_000.0}
    from invoice_core.db import TaxEstimateOverride

    rows = db.query(TaxEstimateOverride).filter_by(year=2026, month=8).all()
    assert len(rows) == 1
    assert rows[0].gross_revenue == 2_700_000.0


def test_save_estimate_overrides_leaves_untouched_months_alone(db):
    tax_service.save_estimate_overrides(db, 2026, {8: 2_500_000.0, 9: 3_000_000.0})
    saved = tax_service.save_estimate_overrides(db, 2026, {8: 2_700_000.0})

    assert saved == {8: 2_700_000.0, 9: 3_000_000.0}
