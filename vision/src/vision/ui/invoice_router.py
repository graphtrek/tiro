"""Invoice-core UI routes served by vision (consumes invoice-core REST API)."""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from vision.clients.invoice_core import InvoiceCoreClient
from vision.ui.utils import dict_to_ns

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(prefix="/ui", tags=["invoice-ui"])


def _client() -> InvoiceCoreClient:
    return InvoiceCoreClient()


def _ctx(client: InvoiceCoreClient, **kwargs) -> dict:
    return {"invoice_count": client.get_invoice_count(), **kwargs}


def _resp(request: Request, template: str, client: InvoiceCoreClient, **kwargs):
    return templates.TemplateResponse(request, template, _ctx(client, **kwargs))


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/")
def dashboard(request: Request):
    client = _client()
    data = client.get_dashboard()
    return _resp(
        request, "ui_dashboard.html", client,
        kpis=dict_to_ns(data.get("kpis", {})),
        recent_invoices=dict_to_ns(data.get("recent_invoices", [])),
        recent_transactions=dict_to_ns(data.get("recent_transactions", [])),
        last_sync=dict_to_ns(data.get("last_sync")) if data.get("last_sync") else None,
        top_suppliers=dict_to_ns(data.get("top_suppliers", [])),
    )


# ── Invoices ──────────────────────────────────────────────────────────────────

@router.get("/invoices")
def invoices_page(
    request: Request,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    payment_status: Optional[str] = None,
    has_pdf: Optional[str] = None,
    supplier_name: Optional[str] = None,
):
    client = _client()
    rows = dict_to_ns(client.get_invoices(
        date_from=str(date_from) if date_from else None,
        date_to=str(date_to) if date_to else None,
        status=payment_status,
        has_pdf=has_pdf,
        supplier_name=supplier_name,
    ))
    is_partial = request.headers.get("HX-Request") and not request.headers.get("HX-Boosted")
    template = "partials/invoice_table.html" if is_partial else "invoices.html"
    return _resp(request, template, client, rows=rows)


@router.get("/invoices/{invoice_id:int}")
def invoice_detail_page(request: Request, invoice_id: int):
    client = _client()
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", client, invoice=dict_to_ns(data))


@router.get("/invoices/{invoice_id:int}/modal")
def invoice_detail_modal(request: Request, invoice_id: int):
    client = _client()
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "partials/invoice_detail_modal.html", client, invoice=dict_to_ns(data))


# ── Invoice Files ─────────────────────────────────────────────────────────────

@router.get("/invoice-files")
def invoice_files_page(request: Request, linked: Optional[str] = None):
    client = _client()
    rows = dict_to_ns(client.get_invoice_files(linked=linked))
    return _resp(request, "invoice_files.html", client, rows=rows)


@router.get("/invoice-files/{file_id:int}/pdf")
def invoice_file_pdf(file_id: int):
    client = _client()
    return RedirectResponse(f"{client.base_url}/api/v1/invoice-files/{file_id}/pdf")


# ── Suppliers ─────────────────────────────────────────────────────────────────

@router.get("/suppliers")
def suppliers_page(request: Request):
    client = _client()
    rows = dict_to_ns(client.get_suppliers())
    summary = dict_to_ns(client.get_supplier_summary())
    is_partial = request.headers.get("HX-Request") and not request.headers.get("HX-Boosted")
    template = "partials/supplier_table.html" if is_partial else "suppliers.html"
    return _resp(request, template, client, rows=rows, summary=summary)


@router.get("/suppliers/{supplier_id:int}")
def supplier_detail_page(request: Request, supplier_id: int):
    client = _client()
    data = client.get_supplier(supplier_id)
    if not data:
        raise HTTPException(status_code=404, detail="Szállító nem található")
    return _resp(request, "supplier_detail.html", client, supplier=dict_to_ns(data))


# ── Customers ─────────────────────────────────────────────────────────────────

@router.get("/customers")
def customers_page(request: Request):
    client = _client()
    rows = dict_to_ns(client.get_customers())
    return _resp(request, "customers.html", client, rows=rows)


@router.get("/customers/{customer_id:int}")
def customer_detail_page(request: Request, customer_id: int):
    client = _client()
    data = client.get_customer(customer_id)
    if not data:
        raise HTTPException(status_code=404, detail="Vevő nem található")
    return _resp(request, "customer_detail.html", client, customer=dict_to_ns(data))


# ── Transactions ──────────────────────────────────────────────────────────────

@router.get("/transactions")
def transactions_page(
    request: Request,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    linked: Optional[str] = None,
    partner_name: Optional[str] = None,
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
):
    client = _client()
    rows = dict_to_ns(client.get_transactions(
        date_from=str(date_from) if date_from else None,
        date_to=str(date_to) if date_to else None,
        linked=linked,
        partner_name=partner_name,
        amount_min=amount_min,
        amount_max=amount_max,
    ))
    bank_balances = dict_to_ns(client.get_bank_balances())
    is_partial = request.headers.get("HX-Request") and not request.headers.get("HX-Boosted")
    template = "partials/transaction_table.html" if is_partial else "transactions.html"
    return _resp(request, template, client, rows=rows, bank_balances=bank_balances)


@router.get("/transactions/{transaction_id:int}")
def transaction_detail_partial(request: Request, transaction_id: int):
    client = _client()
    data = client.get_transaction(transaction_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(request, "partials/transaction_detail.html", client, tx=dict_to_ns(data))


# ── Manual link / unlink (Invoice ↔ InvoiceFile) ─────────────────────────────

@router.post("/invoices/{invoice_id}/invoice-file/link")
def invoice_link_file(request: Request, invoice_id: int, file_id: int = Form(...)):
    client = _client()
    client.link_invoice_to_file(invoice_id, file_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", client, invoice=dict_to_ns(data))


@router.post("/invoices/{invoice_id}/invoice-file/unlink")
def invoice_unlink_file(request: Request, invoice_id: int):
    client = _client()
    client.unlink_invoice_from_file(invoice_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", client, invoice=dict_to_ns(data))


# ── Manual link / unlink (BankTransaction ↔ InvoiceFile) ─────────────────────

@router.post("/transactions/{txn_id}/invoice-file/link")
def transaction_link_file(request: Request, txn_id: int, file_id: int = Form(...)):
    client = _client()
    client.link_transaction_to_file(txn_id, file_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(request, "partials/transaction_detail.html", client, tx=dict_to_ns(data))


@router.post("/transactions/{txn_id}/invoice-file/unlink")
def transaction_unlink_file(request: Request, txn_id: int):
    client = _client()
    client.unlink_transaction_from_file(txn_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(request, "partials/transaction_detail.html", client, tx=dict_to_ns(data))


# ── Manual link / unlink (Invoice ↔ BankTransaction M2M) ─────────────────────

@router.post("/invoices/{invoice_id}/transactions/{txn_id}/link")
def invoice_link_transaction(request: Request, invoice_id: int, txn_id: int):
    client = _client()
    client.link_invoice_transaction(invoice_id, txn_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", client, invoice=dict_to_ns(data))


@router.post("/invoices/{invoice_id}/transactions/{txn_id}/unlink")
def invoice_unlink_transaction(request: Request, invoice_id: int, txn_id: int):
    client = _client()
    client.unlink_invoice_transaction(invoice_id, txn_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", client, invoice=dict_to_ns(data))


# ── Manual link / unlink (BankTransaction ↔ Invoice, transaction-side) ───────
# These are the same M2M link/unlink as the invoice-side routes above, but they
# return the transaction detail partial so they can be used from the tx offcanvas.

@router.post("/transactions/{txn_id}/invoices/{invoice_id}/link")
def transaction_link_invoice(request: Request, txn_id: int, invoice_id: int):
    client = _client()
    client.link_invoice_transaction(invoice_id, txn_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(request, "partials/transaction_detail.html", client, tx=dict_to_ns(data))


@router.post("/transactions/{txn_id}/invoices/{invoice_id}/unlink")
def transaction_unlink_invoice(request: Request, txn_id: int, invoice_id: int):
    client = _client()
    client.unlink_invoice_transaction(invoice_id, txn_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(request, "partials/transaction_detail.html", client, tx=dict_to_ns(data))


# ── Picker routes (HTMX-loaded candidate lists for modal) ─────────────────────

@router.get("/picker/invoice-files")
def picker_invoice_files(
    request: Request,
    source_type: Optional[str] = None,
    source_id: Optional[int] = None,
):
    client = _client()
    rows = dict_to_ns(client.get_invoice_files())
    tx = None
    invoice = None
    if source_type == "invoice":
        link_url_prefix = f"/ui/invoices/{source_id}/invoice-file/link"
        hx_target = "body"
        if source_id:
            inv_data = client.get_invoice(source_id)
            if inv_data:
                invoice = dict_to_ns(inv_data)
    else:
        link_url_prefix = f"/ui/transactions/{source_id}/invoice-file/link"
        hx_target = "#tx-offcanvas-body"
        if source_id:
            txn_data = client.get_transaction(source_id)
            if txn_data:
                tx = dict_to_ns(txn_data)
    return _resp(
        request, "partials/picker_invoice_files.html", client,
        rows=rows,
        link_url_prefix=link_url_prefix,
        hx_target=hx_target,
        tx=tx,
        invoice=invoice,
    )


@router.get("/picker/transactions")
def picker_transactions(
    request: Request,
    invoice_id: Optional[int] = None,
):
    client = _client()
    rows = dict_to_ns(client.get_transactions())
    return _resp(
        request, "partials/picker_transactions.html", client,
        rows=rows,
        invoice_id=invoice_id,
    )


@router.get("/picker/invoices")
def picker_invoices(
    request: Request,
    txn_id: Optional[int] = None,
):
    client = _client()
    rows = dict_to_ns(client.get_invoices())
    tx = None
    if txn_id:
        txn_data = client.get_transaction(txn_id)
        if txn_data:
            already_linked = set(txn_data.get("invoice_ids", []))
            rows = [r for r in rows if r.id not in already_linked]
            tx = dict_to_ns(txn_data)
    return _resp(
        request, "partials/picker_invoices.html", client,
        rows=rows,
        txn_id=txn_id,
        tx=tx,
    )


# ── Dividend report ───────────────────────────────────────────────────────────

@router.get("/dividend")
def dividend_page(request: Request, year: Optional[int] = None):
    from datetime import date as _date
    client = _client()
    effective_year = year or _date.today().year
    report = dict_to_ns(client.get_dividend_report(year=effective_year))
    return _resp(request, "dividend.html", client, report=report, year=effective_year)


# ── Adók (tax payments) ───────────────────────────────────────────────────────

@router.get("/adok")
def adok_page(request: Request, year: Optional[int] = None):
    from datetime import date as _date
    client = _client()
    effective_year = year or _date.today().year
    raw = client.get_tax_report(year=effective_year)
    report = dict_to_ns(raw)
    # totals_by_type and row.totals are dicts keyed by tax label strings with spaces/hyphens
    # ("NAV ÁFA", "HIPA - Késedelmi"); the template calls .get() which requires plain dicts.
    # dict_to_ns() converts them to SimpleNamespace, breaking .get() — restore them here.
    report.totals_by_type = raw.get("totals_by_type", {})
    for m, raw_m in zip(report.monthly or [], raw.get("monthly", [])):
        m.totals = raw_m.get("totals", {})
    return _resp(request, "adok.html", client, report=report, year=effective_year)


# ── Sync ──────────────────────────────────────────────────────────────────────

@router.get("/sync")
def sync_page(request: Request):
    client = _client()
    sync_logs = dict_to_ns(client.get_sync_logs())
    return _resp(request, "sync.html", client, sync_logs=sync_logs, result=None)


@router.post("/sync/trigger")
def sync_trigger(
    request: Request,
    date_from: Optional[str] = Form(None),
    date_to: Optional[str] = Form(None),
    sync_mode: Optional[str] = Form("full"),
):
    client = _client()
    t0 = time.monotonic()
    result_data = client.trigger_sync(
        date_from=date_from or None,
        date_to=date_to or None,
        sync_mode=sync_mode or "full",
    )
    elapsed = time.monotonic() - t0
    result = dict_to_ns(result_data)
    ctx = _ctx(client, result=result, duration_s=elapsed)
    return templates.TemplateResponse(request, "partials/sync_result.html", ctx)
