"""Invoice-core UI routes served by vision (consumes invoice-core REST API)."""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Optional

import requests
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import Response
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
        top_customers=dict_to_ns(data.get("top_customers", [])),
        monthly_finance=data.get("monthly_finance", []),
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
    try:
        upstream = client.get_invoice_file_pdf(file_id)
    except requests.RequestException:
        raise HTTPException(status_code=404, detail="PDF nem található")
    headers = {}
    content_disposition = upstream.headers.get("content-disposition")
    if content_disposition:
        headers["content-disposition"] = content_disposition
    return Response(
        content=upstream.content,
        media_type=upstream.headers.get("content-type", "application/pdf"),
        headers=headers,
    )


@router.delete("/invoice-files/{file_id:int}/delete")
def invoice_file_delete(request: Request, file_id: int):
    client = _client()
    client.delete_invoice_file(file_id)
    rows = dict_to_ns(client.get_invoice_files())
    return _resp(request, "partials/invoice_file_table.html", client, rows=rows)


# ── Suppliers ─────────────────────────────────────────────────────────────────

@router.get("/suppliers")
def suppliers_page(request: Request):
    client = _client()
    rows = dict_to_ns(client.get_suppliers())
    summary = dict_to_ns(client.get_supplier_summary())
    is_partial = request.headers.get("HX-Request") and not request.headers.get("HX-Boosted")
    template = "partials/supplier_table.html" if is_partial else "suppliers.html"
    return _resp(request, template, client, rows=rows, summary=summary)


@router.post("/suppliers")
def create_supplier(
    request: Request,
    name: str = Form(...),
    tax_id: str = Form(""),
    address: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    iban: str = Form(""),
    bban: str = Form(""),
):
    client = _client()
    result = client.create_supplier(
        name=name, tax_id=tax_id or None, address=address or None,
        email=email or None, phone=phone or None, iban=iban or None, bban=bban or None,
    )
    rows = dict_to_ns(client.get_suppliers())
    summary = dict_to_ns(client.get_supplier_summary())
    return _resp(request, "suppliers.html", client, rows=rows, summary=summary, error=result.get("error"))


@router.get("/suppliers/{supplier_id:int}")
def supplier_detail_page(request: Request, supplier_id: int):
    client = _client()
    data = client.get_supplier(supplier_id)
    if not data:
        raise HTTPException(status_code=404, detail="Szállító nem található")
    return _resp(request, "supplier_detail.html", client, supplier=dict_to_ns(data))


@router.post("/suppliers/{supplier_id:int}")
def update_supplier(
    request: Request,
    supplier_id: int,
    name: str = Form(...),
    tax_id: str = Form(""),
    address: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    iban: str = Form(""),
    bban: str = Form(""),
):
    client = _client()
    result = client.update_supplier(
        supplier_id, name=name, tax_id=tax_id or None, address=address or None,
        email=email or None, phone=phone or None, iban=iban or None, bban=bban or None,
    )
    data = client.get_supplier(supplier_id)
    if not data:
        raise HTTPException(status_code=404, detail="Szállító nem található")
    return _resp(request, "supplier_detail.html", client, supplier=dict_to_ns(data), error=result.get("error"))


@router.delete("/suppliers/{supplier_id:int}/delete")
def delete_supplier(request: Request, supplier_id: int):
    client = _client()
    result = client.delete_supplier(supplier_id)
    if result.get("error"):
        data = client.get_supplier(supplier_id)
        return _resp(request, "supplier_detail.html", client, supplier=dict_to_ns(data), error=result["error"])
    return Response(status_code=200, headers={"HX-Redirect": "/ui/suppliers"})


# ── Customers ─────────────────────────────────────────────────────────────────

@router.get("/customers")
def customers_page(request: Request):
    client = _client()
    rows = dict_to_ns(client.get_customers())
    return _resp(request, "customers.html", client, rows=rows)


@router.post("/customers")
def create_customer(
    request: Request,
    name: str = Form(...),
    tax_id: str = Form(""),
    address: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    payment_terms: str = Form(""),
    iban: str = Form(""),
    bban: str = Form(""),
):
    client = _client()
    result = client.create_customer(
        name=name, tax_id=tax_id or None, address=address or None,
        email=email or None, phone=phone or None,
        payment_terms=int(payment_terms) if payment_terms else None,
        iban=iban or None, bban=bban or None,
    )
    rows = dict_to_ns(client.get_customers())
    return _resp(request, "customers.html", client, rows=rows, error=result.get("error"))


@router.get("/customers/{customer_id:int}")
def customer_detail_page(request: Request, customer_id: int):
    client = _client()
    data = client.get_customer(customer_id)
    if not data:
        raise HTTPException(status_code=404, detail="Vevő nem található")
    return _resp(request, "customer_detail.html", client, customer=dict_to_ns(data))


@router.post("/customers/{customer_id:int}")
def update_customer(
    request: Request,
    customer_id: int,
    name: str = Form(...),
    tax_id: str = Form(""),
    address: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    payment_terms: str = Form(""),
    iban: str = Form(""),
    bban: str = Form(""),
):
    client = _client()
    result = client.update_customer(
        customer_id, name=name, tax_id=tax_id or None, address=address or None,
        email=email or None, phone=phone or None,
        payment_terms=int(payment_terms) if payment_terms else None,
        iban=iban or None, bban=bban or None,
    )
    data = client.get_customer(customer_id)
    if not data:
        raise HTTPException(status_code=404, detail="Vevő nem található")
    return _resp(request, "customer_detail.html", client, customer=dict_to_ns(data), error=result.get("error"))


@router.delete("/customers/{customer_id:int}/delete")
def delete_customer(request: Request, customer_id: int):
    client = _client()
    result = client.delete_customer(customer_id)
    if result.get("error"):
        data = client.get_customer(customer_id)
        return _resp(request, "customer_detail.html", client, customer=dict_to_ns(data), error=result["error"])
    return Response(status_code=200, headers={"HX-Redirect": "/ui/customers"})


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


# ── Note and manual Fizetve ───────────────────────────────────────────────────

@router.post("/invoices/{invoice_id}/note")
def invoice_save_note(request: Request, invoice_id: int, note: str = Form("")):
    client = _client()
    client.patch_invoice(invoice_id, note=note)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", client, invoice=dict_to_ns(data))


@router.post("/invoices/{invoice_id}/fizetve")
def invoice_set_fizetve(request: Request, invoice_id: int, locked: str = Form("true")):
    client = _client()
    if locked == "true":
        client.patch_invoice(invoice_id, payment_status_locked=True, payment_status="PAID")
    else:
        client.patch_invoice(invoice_id, payment_status_locked=False)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", client, invoice=dict_to_ns(data))


# ── Manual link / unlink (Invoice ↔ InvoiceFile) ─────────────────────────────

@router.post("/invoices/{invoice_id}/invoice-file/link")
def invoice_link_file(request: Request, invoice_id: int, file_id: int = Form(...)):
    client = _client()
    result = client.link_invoice_to_file(invoice_id, file_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error"))


@router.post("/invoices/{invoice_id}/invoice-file/unlink")
def invoice_unlink_file(request: Request, invoice_id: int):
    client = _client()
    result = client.unlink_invoice_from_file(invoice_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error"))


# ── Manual link / unlink (Invoice ↔ Supplier / Customer) ─────────────────────

@router.post("/invoices/{invoice_id}/supplier/link")
def invoice_link_supplier(request: Request, invoice_id: int, supplier_id: int = Form(...)):
    client = _client()
    result = client.link_invoice_supplier(invoice_id, supplier_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error"))


@router.post("/invoices/{invoice_id}/supplier/unlink")
def invoice_unlink_supplier(request: Request, invoice_id: int):
    client = _client()
    result = client.unlink_invoice_supplier(invoice_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error"))


@router.post("/invoices/{invoice_id}/customer/link")
def invoice_link_customer(request: Request, invoice_id: int, customer_id: int = Form(...)):
    client = _client()
    result = client.link_invoice_customer(invoice_id, customer_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error"))


@router.post("/invoices/{invoice_id}/customer/unlink")
def invoice_unlink_customer(request: Request, invoice_id: int):
    client = _client()
    result = client.unlink_invoice_customer(invoice_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error"))


@router.post("/invoices/{invoice_id}/supplier/create-and-link")
def invoice_create_and_link_supplier(
    request: Request,
    invoice_id: int,
    name: str = Form(...),
    tax_id: str = Form(""),
    address: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    iban: str = Form(""),
    bban: str = Form(""),
):
    client = _client()
    result = client.create_supplier(
        name=name, tax_id=tax_id or None, address=address or None,
        email=email or None, phone=phone or None, iban=iban or None, bban=bban or None,
    )
    if not result.get("error"):
        link_result = client.link_invoice_supplier(invoice_id, result["id"])
        result = {"error": link_result.get("error")} if link_result.get("error") else result
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error"))


@router.post("/invoices/{invoice_id}/customer/create-and-link")
def invoice_create_and_link_customer(
    request: Request,
    invoice_id: int,
    name: str = Form(...),
    tax_id: str = Form(""),
    address: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    payment_terms: str = Form(""),
    iban: str = Form(""),
    bban: str = Form(""),
):
    client = _client()
    result = client.create_customer(
        name=name, tax_id=tax_id or None, address=address or None,
        email=email or None, phone=phone or None,
        payment_terms=int(payment_terms) if payment_terms else None,
        iban=iban or None, bban=bban or None,
    )
    if not result.get("error"):
        link_result = client.link_invoice_customer(invoice_id, result["id"])
        result = {"error": link_result.get("error")} if link_result.get("error") else result
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error"))


# ── Manual link / unlink (BankTransaction ↔ InvoiceFile) ─────────────────────

@router.post("/transactions/{txn_id}/invoice-file/link")
def transaction_link_file(request: Request, txn_id: int, file_id: int = Form(...)):
    client = _client()
    result = client.link_transaction_to_file(txn_id, file_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(request, "partials/transaction_detail.html", client, tx=dict_to_ns(data), error=result.get("error"))


@router.post("/transactions/{txn_id}/invoice-file/unlink")
def transaction_unlink_file(request: Request, txn_id: int):
    client = _client()
    result = client.unlink_transaction_from_file(txn_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(request, "partials/transaction_detail.html", client, tx=dict_to_ns(data), error=result.get("error"))


# ── Manual link / unlink (BankTransaction ↔ Supplier / Customer) ─────────────

@router.post("/transactions/{txn_id}/supplier/link")
def transaction_link_supplier(request: Request, txn_id: int, supplier_id: int = Form(...)):
    client = _client()
    result = client.link_transaction_supplier(txn_id, supplier_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(request, "partials/transaction_detail.html", client, tx=dict_to_ns(data), error=result.get("error"))


@router.post("/transactions/{txn_id}/supplier/unlink")
def transaction_unlink_supplier(request: Request, txn_id: int):
    client = _client()
    result = client.unlink_transaction_supplier(txn_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(request, "partials/transaction_detail.html", client, tx=dict_to_ns(data), error=result.get("error"))


@router.post("/transactions/{txn_id}/customer/link")
def transaction_link_customer(request: Request, txn_id: int, customer_id: int = Form(...)):
    client = _client()
    result = client.link_transaction_customer(txn_id, customer_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(request, "partials/transaction_detail.html", client, tx=dict_to_ns(data), error=result.get("error"))


@router.post("/transactions/{txn_id}/customer/unlink")
def transaction_unlink_customer(request: Request, txn_id: int):
    client = _client()
    result = client.unlink_transaction_customer(txn_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(request, "partials/transaction_detail.html", client, tx=dict_to_ns(data), error=result.get("error"))


@router.post("/transactions/{txn_id}/supplier/create-and-link")
def transaction_create_and_link_supplier(
    request: Request,
    txn_id: int,
    name: str = Form(...),
    tax_id: str = Form(""),
    address: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    iban: str = Form(""),
    bban: str = Form(""),
):
    client = _client()
    result = client.create_supplier(
        name=name, tax_id=tax_id or None, address=address or None,
        email=email or None, phone=phone or None, iban=iban or None, bban=bban or None,
    )
    if not result.get("error"):
        link_result = client.link_transaction_supplier(txn_id, result["id"])
        result = {"error": link_result.get("error")} if link_result.get("error") else result
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(request, "partials/transaction_detail.html", client, tx=dict_to_ns(data), error=result.get("error"))


@router.post("/transactions/{txn_id}/customer/create-and-link")
def transaction_create_and_link_customer(
    request: Request,
    txn_id: int,
    name: str = Form(...),
    tax_id: str = Form(""),
    address: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    payment_terms: str = Form(""),
    iban: str = Form(""),
    bban: str = Form(""),
):
    client = _client()
    result = client.create_customer(
        name=name, tax_id=tax_id or None, address=address or None,
        email=email or None, phone=phone or None,
        payment_terms=int(payment_terms) if payment_terms else None,
        iban=iban or None, bban=bban or None,
    )
    if not result.get("error"):
        link_result = client.link_transaction_customer(txn_id, result["id"])
        result = {"error": link_result.get("error")} if link_result.get("error") else result
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(request, "partials/transaction_detail.html", client, tx=dict_to_ns(data), error=result.get("error"))


# ── Manual link / unlink (Invoice ↔ BankTransaction M2M) ─────────────────────

@router.post("/invoices/{invoice_id}/transactions/{txn_id}/link")
def invoice_link_transaction(request: Request, invoice_id: int, txn_id: int):
    client = _client()
    result = client.link_invoice_transaction(invoice_id, txn_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error"))


@router.post("/invoices/{invoice_id}/transactions/{txn_id}/unlink")
def invoice_unlink_transaction(request: Request, invoice_id: int, txn_id: int):
    client = _client()
    result = client.unlink_invoice_transaction(invoice_id, txn_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error"))


# ── Manual link / unlink (BankTransaction ↔ Invoice, transaction-side) ───────
# These are the same M2M link/unlink as the invoice-side routes above, but they
# return the transaction detail partial so they can be used from the tx offcanvas.

@router.post("/transactions/{txn_id}/invoices/{invoice_id}/link")
def transaction_link_invoice(request: Request, txn_id: int, invoice_id: int):
    client = _client()
    result = client.link_invoice_transaction(invoice_id, txn_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(request, "partials/transaction_detail.html", client, tx=dict_to_ns(data), error=result.get("error"))


@router.post("/transactions/{txn_id}/invoices/{invoice_id}/unlink")
def transaction_unlink_invoice(request: Request, txn_id: int, invoice_id: int):
    client = _client()
    result = client.unlink_invoice_transaction(invoice_id, txn_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(request, "partials/transaction_detail.html", client, tx=dict_to_ns(data), error=result.get("error"))


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
    invoice = None
    if invoice_id:
        inv_data = client.get_invoice(invoice_id)
        if inv_data:
            already_linked = {t.get("id") for t in inv_data.get("bank_transactions", [])}
            rows = [r for r in rows if r.id not in already_linked]
            invoice = dict_to_ns(inv_data)
    return _resp(
        request, "partials/picker_transactions.html", client,
        rows=rows,
        invoice_id=invoice_id,
        invoice=invoice,
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


@router.get("/picker/partners")
def picker_partners(
    request: Request,
    kind: str,
    source_type: Optional[str] = None,
    source_id: Optional[int] = None,
    invoice_id: Optional[int] = None,
):
    if kind not in ("supplier", "customer"):
        raise HTTPException(status_code=422, detail="kind must be 'supplier' or 'customer'")
    if invoice_id and not source_type:
        source_type, source_id = "invoice", invoice_id
    client = _client()
    rows = dict_to_ns(client.get_suppliers() if kind == "supplier" else client.get_customers())
    invoice = None
    tx = None
    if source_type == "transaction":
        link_url_prefix = f"/ui/transactions/{source_id}/{kind}/link"
        create_link_url_prefix = f"/ui/transactions/{source_id}/{kind}/create-and-link"
        hx_target = "#tx-offcanvas-body"
        if source_id:
            txn_data = client.get_transaction(source_id)
            if txn_data:
                tx = dict_to_ns(txn_data)
    else:
        link_url_prefix = f"/ui/invoices/{source_id}/{kind}/link"
        create_link_url_prefix = f"/ui/invoices/{source_id}/{kind}/create-and-link"
        hx_target = "body"
        if source_id:
            inv_data = client.get_invoice(source_id)
            if inv_data:
                invoice = dict_to_ns(inv_data)
    return _resp(
        request, "partials/picker_partners.html", client,
        rows=rows,
        kind=kind,
        link_url_prefix=link_url_prefix,
        create_link_url_prefix=create_link_url_prefix,
        hx_target=hx_target,
        invoice=invoice,
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

    raw_estimate = client.get_tax_estimate_report(year=effective_year)
    # "Havi bontás" covers the whole year's actual invoice-backed data, so its
    # header shows the real (non-projected) gross revenue recorded so far —
    # computed before the monthly list below is filtered down to just the
    # upcoming months for "Becsült adók".
    report.gross_revenue = sum(
        m.get("gross_revenue", 0) for m in raw_estimate.get("monthly", []) if not m.get("is_projected")
    )

    # "Becsült adók" is meant to look ahead only: drop any month before the
    # current one (already elapsed, regardless of whether it shows up in
    # "Havi bontás") and any month already shown in "Havi bontás" (actual tax
    # payments) above, so the two tables never repeat a month.
    current_month_key = _date.today().strftime("%Y-%m")
    paid_months = {m.get("month") for m in raw.get("monthly", [])}
    upcoming = [
        m for m in raw_estimate.get("monthly", [])
        if m.get("month") >= current_month_key and m.get("month") not in paid_months
    ]
    raw_estimate["monthly"] = upcoming
    estimate_fields = ["revenue", "gross_revenue", "expenses", "vat_payable", "tao_tax", "hipa_tax", "szja_tax", "szocho_tax", "total"]
    raw_estimate["totals"] = {
        "month": "Összesen",
        "is_projected": False,
        **{f: sum(m.get(f, 0) for m in upcoming) for f in estimate_fields},
    }

    # Only estimate the tax types actually active in "Havi bontás" this year
    # (its columns are the tax-account labels with a nonzero yearly total),
    # so both tables show the same set of taxes. Labels with no rate-based
    # estimate (e.g. "Iparkamara", "HIPA - Késedelmi") fall back to 0/dash,
    # same as "Havi bontás" already does for months with no payment.
    estimate_label_map = {
        "NAV ÁFA": "vat_payable",
        "NAV TAO": "tao_tax",
        "HIPA": "hipa_tax",
        "NAV SZJA": "szja_tax",
        "NAV Szochó": "szocho_tax",
    }
    active_labels = [label for label in report.tax_labels if report.totals_by_type.get(label, 0)]
    for m in upcoming:
        m["label_totals"] = {label: m.get(estimate_label_map[label], 0.0) for label in active_labels if label in estimate_label_map}
    raw_estimate["totals"]["label_totals"] = {
        label: raw_estimate["totals"].get(estimate_label_map[label], 0.0) for label in active_labels if label in estimate_label_map
    }

    estimate = dict_to_ns(raw_estimate)
    for m, raw_m in zip(estimate.monthly or [], upcoming):
        m.label_totals = raw_m.get("label_totals", {})
    estimate.totals.label_totals = raw_estimate["totals"].get("label_totals", {})
    return _resp(
        request, "adok.html", client,
        report=report, estimate=estimate, estimate_labels=active_labels, year=effective_year,
    )


# ── Sync ──────────────────────────────────────────────────────────────────────

@router.get("/sync")
def sync_page(request: Request):
    client = _client()
    sync_logs = dict_to_ns(client.get_sync_logs())
    pending = dict_to_ns(client.get_pending_sync_counts())
    return _resp(request, "sync.html", client, sync_logs=sync_logs, result=None, pending=pending)


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
    pending = dict_to_ns(client.get_pending_sync_counts())
    ctx = _ctx(client, result=result, duration_s=elapsed, pending=pending)
    return templates.TemplateResponse(request, "partials/sync_result.html", ctx)
