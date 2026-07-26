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


class _FixedDate(date):
    """A `date` subclass whose `.today()` is pinned, so month-based projection
    logic in `get_tax_estimate` is deterministic in tests."""

    @classmethod
    def today(cls):
        return date(2026, 7, 15)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(tax_service, "date", _FixedDate)


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
