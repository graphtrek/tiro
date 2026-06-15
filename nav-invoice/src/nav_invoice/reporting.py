"""Adatszolgáltatás (Reporting) module.

Implements ``manageInvoice`` (with automatic ``tokenExchange``) and
``queryTransactionStatus`` against the NAV 3.0 REST API.
"""

import base64
import logging
from datetime import date
from typing import Optional, Union
from xml.sax.saxutils import escape

from nav_invoice.auth import request_token
from nav_invoice.client import NavClient, NavApiError, findall, findtext
from nav_invoice.config import Settings, get_settings
from nav_invoice.models import (
    ManageInvoiceOperation,
    SubmitInvoiceRequest,
    SubmitInvoiceResponse,
    TransactionResult,
)

logger = logging.getLogger(__name__)

DATA_NS = "http://schemas.nav.gov.hu/OSA/3.0/data"
BASE_NS = "http://schemas.nav.gov.hu/OSA/3.0/base"
COMMON_DATA_NS = "http://schemas.nav.gov.hu/NTCA/1.0/common"


# ── manageInvoice ───────────────────────────────────────

def manage_invoice(
    invoice_xml: str,
    operation: Union[str, ManageInvoiceOperation] = ManageInvoiceOperation.CREATE,
    settings: Optional[Settings] = None,
) -> TransactionResult:
    """Submit a single invoice (szakmai XML) to NAV.

    Performs ``tokenExchange`` automatically, base64-encodes the invoice,
    signs the request (including the per-invoice hash) and posts to
    ``/manageInvoice``. Returns a :class:`TransactionResult` with the
    ``transactionId`` used by ``queryTransactionStatus``.
    """
    if settings is None:
        settings = get_settings()
    if isinstance(operation, ManageInvoiceOperation):
        operation = operation.value

    token = request_token(settings)["token"]
    b64_invoice = base64.b64encode(invoice_xml.encode("utf-8")).decode("ascii")

    body = (
        f"<exchangeToken>{escape(token)}</exchangeToken>"
        "<invoiceOperations>"
        "<compressedContent>false</compressedContent>"
        "<invoiceOperation>"
        "<index>1</index>"
        f"<invoiceOperation>{operation}</invoiceOperation>"
        f"<invoiceData>{b64_invoice}</invoiceData>"
        "</invoiceOperation>"
        "</invoiceOperations>"
    )

    client = NavClient(settings)
    payload = client.build_request(
        "ManageInvoiceRequest",
        body,
        invoices=[(operation, b64_invoice)],
    )
    root = client.post("/manageInvoice", payload)

    transaction_id = findtext(root, "transactionId")
    return TransactionResult(
        transaction_id=transaction_id,
        success=bool(transaction_id),
        message="Adatszolgáltatás beküldve" if transaction_id else "Ismeretlen hiba",
    )


# ── queryTransactionStatus ──────────────────────────────

def query_transaction_status(
    transaction_id: str,
    settings: Optional[Settings] = None,
) -> dict:
    """Query the processing status of a previously submitted transaction."""
    if settings is None:
        settings = get_settings()

    body = (
        f"<transactionId>{escape(transaction_id)}</transactionId>"
        "<returnOriginalRequest>false</returnOriginalRequest>"
    )

    client = NavClient(settings)
    payload = client.build_request("QueryTransactionStatusRequest", body)
    root = client.post("/queryTransactionStatus", payload)

    results = []
    for el in findall(root, "processingResult"):
        results.append(
            {
                "index": findtext(el, "index"),
                "status": findtext(el, "invoiceStatus"),
            }
        )

    return {"transaction_id": transaction_id, "results": results}


# ── Invoice XML builder (best-effort, from legacy model) ─

def _build_invoice_xml(request: SubmitInvoiceRequest, settings: Settings) -> str:
    """Build a minimal NAV ``InvoiceData`` XML from the legacy model.

    This produces a structurally complete single-VAT-rate invoice. Complex
    invoices should be built with a dedicated invoice generator and submitted
    via :func:`manage_invoice`.
    """
    h = request.invoice.header
    issue = h.keltes_datuma.isoformat() if h.keltes_datuma else date.today().isoformat()
    net = h.netto_total or (h.bruttototal / 1.27 if h.bruttototal else 0.0)
    vat = h.ado_total or (h.bruttototal - net if h.bruttototal else 0.0)
    gross = h.bruttototal or (net + vat)

    lines_xml = ""
    for i, item in enumerate(request.invoice.line_items, start=1):
        line_net = item.egysagar * item.mennyiseg
        lines_xml += (
            "<line>"
            f"<lineNumber>{i}</lineNumber>"
            "<lineExpressionIndicator>false</lineExpressionIndicator>"
            f"<lineDescription>{escape(item.tétel_leiras)}</lineDescription>"
            f"<quantity>{item.mennyiseg}</quantity>"
            f"<unitPrice>{item.egysagar}</unitPrice>"
            "<lineAmountsNormal>"
            "<lineNetAmountData>"
            f"<lineNetAmount>{line_net}</lineNetAmount>"
            f"<lineNetAmountHUF>{line_net}</lineNetAmountHUF>"
            "</lineNetAmountData>"
            f"<lineVatRate><vatPercentage>{item.ado_kulcs / 100}</vatPercentage></lineVatRate>"
            "</lineAmountsNormal>"
            "</line>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<InvoiceData xmlns="{DATA_NS}" xmlns:base="{BASE_NS}" '
        f'xmlns:common="{COMMON_DATA_NS}">'
        f"<invoiceNumber>{escape(h.szamlaszam)}</invoiceNumber>"
        f"<invoiceIssueDate>{issue}</invoiceIssueDate>"
        "<completenessIndicator>false</completenessIndicator>"
        "<invoiceMain><invoice><invoiceHead>"
        "<supplierInfo>"
        f"<supplierTaxNumber><base:taxpayerId>{settings.tax_number}</base:taxpayerId>"
        "</supplierTaxNumber>"
        f"<supplierName>{escape(h.szamlazas_vegezo)}</supplierName>"
        "</supplierInfo>"
        "<customerInfo>"
        "<customerVatStatus>DOMESTIC</customerVatStatus>"
        f"<customerName>{escape(h.vevo_neve)}</customerName>"
        "</customerInfo>"
        "<invoiceDetail>"
        "<invoiceCategory>NORMAL</invoiceCategory>"
        f"<invoiceDeliveryDate>{issue}</invoiceDeliveryDate>"
        "<currencyCode>HUF</currencyCode>"
        "<exchangeRate>1</exchangeRate>"
        "<paymentMethod>TRANSFER</paymentMethod>"
        "<invoiceAppearance>ELECTRONIC</invoiceAppearance>"
        "</invoiceDetail>"
        "</invoiceHead>"
        f"<invoiceLines><mergedItemIndicator>false</mergedItemIndicator>{lines_xml}</invoiceLines>"
        "<invoiceSummary><summaryNormal>"
        "<summaryByVatRate>"
        "<vatRate><vatPercentage>0.27</vatPercentage></vatRate>"
        f"<vatRateNetData><vatRateNetAmount>{net}</vatRateNetAmount>"
        f"<vatRateNetAmountHUF>{net}</vatRateNetAmountHUF></vatRateNetData>"
        f"<vatRateVatData><vatRateVatAmount>{vat}</vatRateVatAmount>"
        f"<vatRateVatAmountHUF>{vat}</vatRateVatAmountHUF></vatRateVatData>"
        "</summaryByVatRate>"
        f"<invoiceNetAmount>{net}</invoiceNetAmount>"
        f"<invoiceNetAmountHUF>{net}</invoiceNetAmountHUF>"
        f"<invoiceVatAmount>{vat}</invoiceVatAmount>"
        f"<invoiceVatAmountHUF>{vat}</invoiceVatAmountHUF>"
        "</summaryNormal>"
        f"<summaryGrossData><invoiceGrossAmount>{gross}</invoiceGrossAmount>"
        f"<invoiceGrossAmountHUF>{gross}</invoiceGrossAmountHUF></summaryGrossData>"
        "</invoiceSummary>"
        "</invoice></invoiceMain>"
        "</InvoiceData>"
    )


def submit_invoice(
    request: Optional[SubmitInvoiceRequest] = None,
    settings: Optional[Settings] = None,
) -> SubmitInvoiceResponse:
    """Legacy wrapper: build an invoice from the model and call manageInvoice."""
    if settings is None:
        settings = get_settings()
    if request is None or request.invoice is None or request.invoice.header is None:
        return SubmitInvoiceResponse(success=False, message="Hiányzó számlaadat.")

    try:
        invoice_xml = _build_invoice_xml(request, settings)
        result = manage_invoice(invoice_xml, ManageInvoiceOperation.CREATE, settings)
    except NavApiError as exc:
        return SubmitInvoiceResponse(success=False, message=str(exc))

    return SubmitInvoiceResponse(
        success=result.success,
        message=result.message,
        submission_id=result.transaction_id,
    )