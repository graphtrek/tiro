"""Lekérdezés (Query) module.

Implements ``queryInvoiceDigest`` (list/search), ``queryInvoiceData``
(single invoice) and ``queryTaxpayer`` against the NAV 3.0 REST API.
"""

import base64
import gzip
import logging
from datetime import date, timedelta
from typing import Optional

from lxml import etree

from nav_invoice import cache as _cache
from nav_invoice.client import NavClient, NavApiError, findall, findtext
from nav_invoice.config import Settings, get_settings
from nav_invoice.models import (
    DigestQueryParams,
    InvoiceDigest,
    InvoiceDirection,
)

logger = logging.getLogger(__name__)


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _to_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── queryInvoiceDigest ──────────────────────────────────

def query_invoice_digest(
    params: Optional[DigestQueryParams] = None,
    settings: Optional[Settings] = None,
) -> list[InvoiceDigest]:
    """List invoices for a date range (kiállító vagy vevő oldal).

    NAV limits the ``invoiceIssueDate`` range to 35 days.
    """
    if settings is None:
        settings = get_settings()
    if params is None:
        params = DigestQueryParams(
            from_date=date.today() - timedelta(days=30),
            to_date=date.today(),
        )

    cache_key = f"digest:{params.from_date}:{params.to_date}:{params.direction.value}:{params.page}"
    cached = _cache.get(cache_key)
    if cached is not None:
        logger.debug("Cache hit: %s", cache_key)
        return cached

    body = (
        f"<page>{params.page}</page>"
        f"<invoiceDirection>{params.direction.value}</invoiceDirection>"
        "<invoiceQueryParams><mandatoryQueryParams><invoiceIssueDate>"
        f"<dateFrom>{params.from_date.isoformat()}</dateFrom>"
        f"<dateTo>{params.to_date.isoformat()}</dateTo>"
        "</invoiceIssueDate></mandatoryQueryParams></invoiceQueryParams>"
    )

    client = NavClient(settings)
    payload = client.build_request("QueryInvoiceDigestRequest", body)
    root = client.post("/queryInvoiceDigest", payload)

    result = [_parse_digest(el) for el in findall(root, "invoiceDigest")]
    _cache.set(cache_key, result, settings.cache_ttl_seconds)
    return result


def _parse_digest(element: "etree._Element") -> InvoiceDigest:
    fields: dict[str, str] = {}
    for child in element.iter():
        if child is element:
            continue
        name = _local(child.tag)
        if name not in fields and child.text:
            fields[name] = child.text.strip()

    return InvoiceDigest(
        invoice_number=fields.get("invoiceNumber", ""),
        invoice_operation=fields.get("invoiceOperation", ""),
        invoice_category=fields.get("invoiceCategory", ""),
        invoice_issue_date=fields.get("invoiceIssueDate", ""),
        supplier_tax_number=fields.get("supplierTaxNumber", ""),
        supplier_name=fields.get("supplierName", ""),
        customer_tax_number=fields.get("customerTaxNumber", ""),
        customer_name=fields.get("customerName", ""),
        invoice_net_amount=_to_float(
            fields.get("invoiceNetAmountHUF") or fields.get("invoiceNetAmount", "")
        ),
        invoice_vat_amount=_to_float(
            fields.get("invoiceVatAmountHUF") or fields.get("invoiceVatAmount", "")
        ),
        currency=fields.get("currency", ""),
        ins_date=fields.get("insDate", ""),
    )


# ── queryInvoiceData ────────────────────────────────────

def query_invoice_data(
    invoice_number: str,
    direction: InvoiceDirection = InvoiceDirection.OUTBOUND,
    supplier_tax_number: str = "",
    settings: Optional[Settings] = None,
) -> Optional[str]:
    """Fetch a single invoice and return the decoded business XML string.

    Returns ``None`` if the invoice was not found.
    """
    if settings is None:
        settings = get_settings()

    cache_key = f"data:{invoice_number}:{direction.value}"
    cached = _cache.get(cache_key)
    if cached is not None:
        logger.debug("Cache hit: %s", cache_key)
        return cached

    supplier_xml = (
        f"<supplierTaxNumber>{supplier_tax_number}</supplierTaxNumber>"
        if supplier_tax_number and direction == InvoiceDirection.INBOUND
        else ""
    )
    body = (
        "<invoiceNumberQuery>"
        f"<invoiceNumber>{invoice_number}</invoiceNumber>"
        f"<invoiceDirection>{direction.value}</invoiceDirection>"
        f"{supplier_xml}"
        "</invoiceNumberQuery>"
    )

    client = NavClient(settings)
    payload = client.build_request("QueryInvoiceDataRequest", body)
    root = client.post("/queryInvoiceData", payload)

    encoded = findtext(root, "invoiceData")
    if not encoded:
        return None

    raw = base64.b64decode(encoded)
    compressed = findtext(root, "compressedContentIndicator").lower() == "true"
    if compressed:
        raw = gzip.decompress(raw)

    result = raw.decode("utf-8")
    _cache.set(cache_key, result, settings.cache_ttl_seconds)
    return result


# ── queryTaxpayer ───────────────────────────────────────

def query_taxpayer(
    tax_number: str,
    settings: Optional[Settings] = None,
) -> dict:
    """Validate a Hungarian tax number and return basic taxpayer data."""
    if settings is None:
        settings = get_settings()

    cache_key = f"taxpayer:{tax_number}"
    cached = _cache.get(cache_key)
    if cached is not None:
        logger.debug("Cache hit: %s", cache_key)
        return cached

    body = f"<taxNumber>{tax_number}</taxNumber>"

    client = NavClient(settings)
    payload = client.build_request("QueryTaxpayerRequest", body)
    root = client.post("/queryTaxpayer", payload)

    valid = findtext(root, "taxpayerValidity").lower() == "true"
    result = {
        "valid": valid,
        "name": findtext(root, "taxpayerName"),
        "short_name": findtext(root, "taxpayerShortName"),
    }
    _cache.set(cache_key, result, settings.cache_ttl_seconds)
    return result


# ── Backwards-compatible wrappers (legacy CLI/API) ──────

def list_invoices(params=None, settings: Optional[Settings] = None):
    """Legacy wrapper around :func:`query_invoice_digest`.

    Accepts the old ``InvoiceQueryParams`` and returns ``InvoiceDigest`` items.
    """
    if settings is None:
        settings = get_settings()

    from_date = getattr(params, "from_date", None) or (date.today() - timedelta(days=30))
    to_date = getattr(params, "to_date", None) or date.today()

    digest_params = DigestQueryParams(
        from_date=from_date,
        to_date=to_date,
        direction=InvoiceDirection.OUTBOUND,
    )

    try:
        return query_invoice_digest(digest_params, settings)
    except NavApiError as exc:
        logger.error("Query failed: %s", exc)
        return []


def get_single_invoice(szamlaszam: str, settings: Optional[Settings] = None):
    """Legacy wrapper returning the decoded invoice XML string (or ``None``)."""
    try:
        return query_invoice_data(szamlaszam, settings=settings)
    except NavApiError as exc:
        logger.error("Single invoice query failed: %s", exc)
        return None