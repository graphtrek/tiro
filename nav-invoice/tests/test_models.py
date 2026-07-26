"""Tests for Pydantic models."""

from datetime import UTC, date, datetime

from nav_invoice.models import (
    InvoiceDetail,
    InvoiceHeader,
    InvoiceListEntry,
    InvoiceQueryParams,
    InvoiceStatus,
    InvoiceType,
    SubmitInvoiceRequest,
)


class TestInvoiceHeader:
    def test_create_header(self):
        header = InvoiceHeader(
            szamlaszam="2026051234",
            keltes_datuma=date(2026, 5, 12),
            szamlazas_vegezo="Test Kft.",
        )

        assert header.szamlaszam == "2026051234"
        assert header.szamlazas_vegezo == "Test Kft."

    def test_default_values(self):
        header = InvoiceHeader(
            szamlaszam="123",
            keltes_datuma=datetime.now(tz=UTC).astimezone().date(),
            szamlazas_vegezo="X",
        )

        assert header.szamlatipus == InvoiceType.SML
        assert header.bruttototal == 0.0


class TestInvoiceListEntry:
    def test_create_entry(self):
        entry = InvoiceListEntry(
            szamlaszam="2026051234",
            szamlatipus=InvoiceType.SML,
            keltes_datuma=date(2026, 5, 12),
            bruttototal=100000.0,
        )

        assert entry.szamlaszam == "2026051234"
        assert entry.bruttototal == 100000.0


class TestInvoiceQueryParams:
    def test_empty_params(self):
        params = InvoiceQueryParams()

        assert params.from_date is None
        assert params.to_date is None


class TestSubmitInvoiceRequest:
    def test_create_request(self):
        header = InvoiceHeader(
            szamlaszam="2026051234",
            keltes_datuma=date(2026, 5, 12),
            szamlazas_vegezo="Test Kft.",
        )
        request = SubmitInvoiceRequest(invoice=InvoiceDetail(header=header))

        assert request.invoice is not None


class TestEnums:
    def test_invoice_types(self):
        assert InvoiceType.SML.value == "SML"
        assert InvoiceType.ELSZ.value == "ELSZ"

    def test_invoice_statuses(self):
        assert InvoiceStatus.BEJELENTVE.value == "BEJELENTVE"