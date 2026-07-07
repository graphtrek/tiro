"""A teljes queryInvoiceData üzleti XML (invoiceData gyökérelem) feldolgozása.

A NAV Online Számla 3.0 InvoiceData XSD nyilvánosan dokumentált felépítésén
alapul. Csak azt bontja ki, amire invoice-core-nak szüksége van (cím,
bankszámla, fizetési mód/határidő) — tételsorok és ÁFA-kulcsonkénti
összesítők szándékosan kimaradnak (lásd InvoiceDetailData docstring).
"""

from typing import Optional

from lxml import etree

from nav_invoice.client import child_text, findall
from nav_invoice.models import InvoiceDetailData


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
        ) if part
    )
    parts = [child_text(detail, "postalCode"), child_text(detail, "city"), street]
    return ", ".join(part for part in parts if part)


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
    )
