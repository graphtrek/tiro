"""Annual szocho cap (24x the monthly minimum wage) across dividend + tax estimate.

Capital income (here: the dividend base) only bears szocho until the
individual's szocho-bearing income for the year reaches 24x the monthly minimum
wage -- 7 747 200 Ft in 2026, i.e. at most 1 007 136 Ft of szocho. These tests
pin that ceiling for both services that charge the tax.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from invoice_core.db import Base, Invoice, _InvoiceDirection
from invoice_core.services import dividend_service, tax_service
from invoice_core.services.szocho import capped_szocho, szocho_cap

CAP_2026 = 322_800.0 * 24  # 7 747 200 Ft
MAX_SZOCHO_2026 = CAP_2026 * 0.13  # 1 007 136 Ft


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(tax_service, "today", lambda: date(2026, 12, 31))


def _invoice(db, number, invoice_date, direction, amount_net):
    db.add(
        Invoice(
            invoice_number=number,
            invoice_date=invoice_date,
            direction=direction,
            amount_net=amount_net,
            amount_total=amount_net,
        )
    )
    db.commit()


def test_cap_follows_the_year_and_clamps_to_known_years():
    assert szocho_cap(2026) == pytest.approx(CAP_2026)
    assert szocho_cap(2025) == pytest.approx(290_800.0 * 24)
    # Years outside the published table fall back to the nearest known one.
    assert szocho_cap(2099) == szocho_cap(2026)
    assert szocho_cap(2000) == szocho_cap(2024)


def test_capped_szocho_charges_only_the_part_under_the_cap():
    assert capped_szocho(1_000_000.0, 0.13, 2026) == pytest.approx(130_000.0)
    assert capped_szocho(50_000_000.0, 0.13, 2026) == pytest.approx(MAX_SZOCHO_2026)
    assert capped_szocho(-5_000.0, 0.13, 2026) == 0.0
    # A caller that already used part of the cap only gets the leftover.
    assert capped_szocho(5_000_000.0, 0.13, 2026, cap_remaining=1_000_000.0) == pytest.approx(
        130_000.0
    )


def test_dividend_szocho_stops_at_the_annual_cap(db):
    _invoice(db, "OUT-1", date(2026, 3, 10), _InvoiceDirection.OUTBOUND, 200_000_000.0)

    report = dividend_service.calculate_dividend(db, 2026)

    assert report.net_profit > CAP_2026  # the cap really is the binding constraint
    assert report.szocho_cap == pytest.approx(CAP_2026)
    assert report.szocho_base == pytest.approx(CAP_2026)
    assert report.szocho_tax == pytest.approx(MAX_SZOCHO_2026)
    assert report.net_dividend_with_szocho == pytest.approx(
        report.net_profit - report.szja_tax - MAX_SZOCHO_2026
    )


def test_dividend_below_the_cap_is_charged_in_full(db):
    _invoice(db, "OUT-1", date(2026, 3, 10), _InvoiceDirection.OUTBOUND, 1_000_000.0)

    report = dividend_service.calculate_dividend(db, 2026)

    assert report.net_profit < CAP_2026
    assert report.szocho_base == pytest.approx(report.net_profit)
    assert report.szocho_tax == pytest.approx(report.net_profit * report.szocho_rate)


def test_tax_estimate_spends_the_cap_month_by_month(db):
    # Four months, each with a dividend base well over a quarter of the cap, so
    # the cap runs out partway through the year.
    for month in (1, 2, 3, 4):
        _invoice(db, f"OUT-{month}", date(2026, month, 10), _InvoiceDirection.OUTBOUND, 5_000_000.0)

    report = tax_service.get_tax_estimate(db, 2026)
    rows = {row.month: row for row in report.monthly}

    assert report.szocho_cap == pytest.approx(CAP_2026)
    assert report.totals.szocho_tax == pytest.approx(MAX_SZOCHO_2026)
    assert report.totals.szocho_base == pytest.approx(CAP_2026)

    # Earliest months consume the cap in full; once it is gone, later months
    # with the same revenue are szocho-free.
    assert rows["2026-01"].szocho_tax > 0.0
    assert rows["2026-04"].szocho_tax == 0.0
    assert rows["2026-04"].revenue > 0.0  # not zero merely for lack of revenue

    # Each month's `total` must move with its own szocho, not the uncapped one.
    for row in report.monthly:
        assert row.total == pytest.approx(
            row.vat_payable + row.tao_tax + row.hipa_tax + row.szja_tax + row.szocho_tax
        )
    assert report.totals.total == pytest.approx(sum(row.total for row in report.monthly))


def test_tax_estimate_under_the_cap_is_unaffected(db):
    _invoice(db, "OUT-1", date(2026, 5, 10), _InvoiceDirection.OUTBOUND, 1_000_000.0)

    report = tax_service.get_tax_estimate(db, 2026)
    may = next(row for row in report.monthly if row.month == "2026-05")

    net_profit = may.revenue - may.expenses - may.tao_tax - may.hipa_tax
    assert report.totals.szocho_base < CAP_2026
    assert may.szocho_tax == pytest.approx(net_profit * report.szocho_rate)
