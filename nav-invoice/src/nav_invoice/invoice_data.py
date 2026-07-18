"""A teljes queryInvoiceData üzleti XML (invoiceData gyökérelem) feldolgozása.

A NAV Online Számla 3.0 InvoiceData XSD nyilvánosan dokumentált felépítésén
alapul. Kibontja mindazt, amire invoice-core-nak szüksége van: cím,
bankszámla, fizetési mód/határidő, fejléc-kiegészítők, tételsorok és
ÁFA-kulcsonkénti összesítők.
"""

from typing import Optional

from lxml import etree

from nav_invoice.client import child_text, findall
from nav_invoice.models import InvoiceDetailData, InvoiceLineData, InvoiceVatSummaryData


def _first(element: "etree._Element", local_name: str) -> Optional["etree._Element"]:
    """Return the first descendant of *element* with the given local name."""
    matches = findall(element, local_name)
    return matches[0] if matches else None


def _format_address(address_el: Optional["etree._Element"]) -> str:
    """Format a supplierAddress/customerAddress element into a single display string."""
    if address_el is None:
        return ""
    found = _first(address_el, "detailedAddress")
    detail = found if found is not None else address_el
    street = " ".join(
        part for part in (
            child_text(detail, "streetName"),
            child_text(detail, "publicPlaceCategory"),
            child_text(detail, "houseNumber"),
            child_text(detail, "additionalAddressDetail"),
        ) if part
    )
    parts = [child_text(detail, "postalCode"), child_text(detail, "city"), street]
    return ", ".join(part for part in parts if part)


def _to_float(text: str) -> Optional[float]:
    """Best-effort float parse; returns None for empty/invalid text."""
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_lines(invoice_el: "etree._Element") -> list[InvoiceLineData]:
    """Parse invoiceLines/line entries. Each line is scoped independently so
    sibling lines' amounts never cross-contaminate (child_text searches all
    descendants of the element passed in)."""
    lines_el = _first(invoice_el, "invoiceLines")
    if lines_el is None:
        return []
    result = []
    for line_el in findall(lines_el, "line"):
        result.append(InvoiceLineData(
            line_number=child_text(line_el, "lineNumber"),
            line_description=child_text(line_el, "lineDescription"),
            quantity=_to_float(child_text(line_el, "quantity")),
            unit_of_measure=child_text(line_el, "unitOfMeasure"),
            unit_price=_to_float(child_text(line_el, "unitPrice")),
            line_net_amount=_to_float(child_text(line_el, "lineNetAmount")),
            line_vat_rate=_to_float(child_text(line_el, "vatPercentage")),
            line_vat_amount=_to_float(child_text(line_el, "lineVatAmount")),
            line_gross_amount=_to_float(child_text(line_el, "lineGrossAmountNormal")),
        ))
    return result


def _parse_vat_summary(
    invoice_el: "etree._Element",
) -> tuple[list[InvoiceVatSummaryData], Optional[float], Optional[float], Optional[float]]:
    """Parse invoiceSummary into (per-rate rows, invoice net, invoice vat, invoice gross)."""
    summary_el = _first(invoice_el, "invoiceSummary")
    if summary_el is None:
        return [], None, None, None

    normal_el = _first(summary_el, "summaryNormal")
    rows = []
    net_amount = None
    vat_amount = None
    if normal_el is not None:
        for rate_el in findall(normal_el, "summaryByVatRate"):
            rows.append(InvoiceVatSummaryData(
                vat_rate=_to_float(child_text(rate_el, "vatPercentage")),
                vat_rate_net_amount=_to_float(child_text(rate_el, "vatRateNetAmount")),
                vat_rate_vat_amount=_to_float(child_text(rate_el, "vatRateVatAmount")),
            ))
        net_amount = _to_float(child_text(normal_el, "invoiceNetAmount"))
        vat_amount = _to_float(child_text(normal_el, "invoiceVatAmount"))

    gross_el = _first(summary_el, "summaryGrossData")
    gross_amount = _to_float(child_text(gross_el, "invoiceGrossAmount")) if gross_el is not None else None

    return rows, net_amount, vat_amount, gross_amount


def parse_invoice_data(xml_str: str, invoice_number: str = "") -> InvoiceDetailData:
    """Parse the decoded queryInvoiceData business XML into an InvoiceDetailData."""
    root = etree.fromstring(xml_str.encode("utf-8"))

    # NAV returns either invoiceMain/invoice (normal) or invoiceMain/batchInvoice
    # (modification chains) — batch modification-chain resolution is out of
    # scope, so we just take whichever element is present.
    invoice_el = _first(root, "invoice")
    if invoice_el is None:
        invoice_el = _first(root, "batchInvoice")
    if invoice_el is None:
        invoice_el = root

    supplier_el = _first(invoice_el, "supplierInfo")
    customer_el = _first(invoice_el, "customerInfo")
    detail_el = _first(invoice_el, "invoiceDetail")

    lines = _parse_lines(invoice_el)
    vat_summary, invoice_net_amount, invoice_vat_amount, invoice_gross_amount = _parse_vat_summary(invoice_el)

    return InvoiceDetailData(
        invoice_number=invoice_number,
        supplier_address=_format_address(
            _first(supplier_el, "supplierAddress") if supplier_el is not None else None
        ),
        supplier_bank_account=(
            child_text(supplier_el, "supplierBankAccountNumber") if supplier_el is not None else ""
        ),
        customer_address=_format_address(
            _first(customer_el, "customerAddress") if customer_el is not None else None
        ),
        customer_bank_account=(
            child_text(customer_el, "customerBankAccountNumber") if customer_el is not None else ""
        ),
        payment_method=(child_text(detail_el, "paymentMethod") if detail_el is not None else ""),
        payment_due_date=(child_text(detail_el, "paymentDate") if detail_el is not None else ""),
        invoice_category=(child_text(detail_el, "invoiceCategory") if detail_el is not None else ""),
        delivery_date=(child_text(detail_el, "invoiceDeliveryDate") if detail_el is not None else ""),
        currency_code=(child_text(detail_el, "currencyCode") if detail_el is not None else ""),
        exchange_rate=(_to_float(child_text(detail_el, "exchangeRate")) if detail_el is not None else None),
        invoice_appearance=(child_text(detail_el, "invoiceAppearance") if detail_el is not None else ""),
        invoice_net_amount=invoice_net_amount,
        invoice_vat_amount=invoice_vat_amount,
        invoice_gross_amount=invoice_gross_amount,
        lines=lines,
        vat_summary=vat_summary,
    )
