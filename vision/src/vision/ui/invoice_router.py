"""Invoice-core UI routes served by vision (consumes invoice-core REST API)."""

from __future__ import annotations

import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import requests
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from vision.clients.invoice_core import InvoiceCoreClient
from vision.ui.utils import dict_to_ns, local_today

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter(prefix="/ui", tags=["invoice-ui"])


def _client() -> InvoiceCoreClient:
    return InvoiceCoreClient()


def _ctx(client: InvoiceCoreClient, **kwargs) -> dict:
    return {**kwargs}


def _resp(request: Request, template: str, client: InvoiceCoreClient, **kwargs):
    return templates.TemplateResponse(request, template, _ctx(client, **kwargs))


# ── Dashboard ─────────────────────────────────────────────────────────────────


def _fmt_hours(v: float) -> str:
    return f"{v:g}".replace(".", ",")


def _month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def _next_month(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


# Matches the validated 7-slot categorical palette (--series-1..7 in custom.css,
# already used the same way by controlling_reports.html's weekly chart) — projects
# beyond that fold into a single muted "Egyéb" series rather than a generated hue.
_MAX_PROJECT_SERIES = 7
_OTHER_PROJECT_LABEL = "Egyéb"


def _timesheet_series(entries: list[dict]) -> dict:
    """Company-wide hours per timeline bucket, broken down by project — daily,
    monthly, and yearly, each running from the very first timesheet entry ever
    recorded (no rolling window) through today. Project→series-slot assignment
    is ranked by all-time total hours and shared across all three levels, so a
    project keeps the same color everywhere."""
    today = local_today()
    entry_dates = [date.fromisoformat(e["entry_date"]) for e in entries]
    first_date = min(entry_dates) if entry_dates else today

    project_totals: dict[str, float] = {}
    for e in entries:
        project_totals[e["project_code"]] = project_totals.get(e["project_code"], 0.0) + e["hours"]
    ranked_projects = sorted(project_totals, key=lambda p: project_totals[p], reverse=True)
    top_projects = ranked_projects[:_MAX_PROJECT_SERIES]
    has_other = len(ranked_projects) > _MAX_PROJECT_SERIES
    project_labels = top_projects + ([_OTHER_PROJECT_LABEL] if has_other else [])

    def _series_index(project_code: str) -> int:
        if project_code in top_projects:
            return top_projects.index(project_code)
        return len(top_projects)

    def _empty_row() -> list[float]:
        return [0.0] * len(project_labels)

    daily_buckets: dict[str, list[float]] = {}
    d = first_date
    while d <= today:
        daily_buckets[d.isoformat()] = _empty_row()
        d += timedelta(days=1)

    monthly_buckets: dict[str, list[float]] = {}
    m = first_date.replace(day=1)
    this_month = today.replace(day=1)
    while m <= this_month:
        monthly_buckets[_month_key(m)] = _empty_row()
        m = _next_month(m)

    yearly_buckets: dict[str, list[float]] = {
        str(y): _empty_row() for y in range(first_date.year, today.year + 1)
    }

    for e in entries:
        entry_date = e["entry_date"]
        idx = _series_index(e["project_code"])
        if entry_date in daily_buckets:
            daily_buckets[entry_date][idx] += e["hours"]
        month_key = entry_date[:7]
        if month_key in monthly_buckets:
            monthly_buckets[month_key][idx] += e["hours"]
        year_key = entry_date[:4]
        if year_key in yearly_buckets:
            yearly_buckets[year_key][idx] += e["hours"]

    def _rows(buckets: dict[str, list[float]]) -> dict:
        keys = sorted(buckets)
        return {
            "labels": keys,
            "series": [[round(v, 2) for v in buckets[k]] for k in keys],
        }

    return {
        "project_labels": project_labels,
        "daily": _rows(daily_buckets),
        "monthly": _rows(monthly_buckets),
        "yearly": _rows(yearly_buckets),
    }


@router.get("/")
def dashboard(request: Request):
    client = _client()
    data = client.get_dashboard()

    timesheet_entries = client.get_timesheet_entries()
    timesheet_recent = sorted(
        timesheet_entries, key=lambda e: (e["entry_date"], e["id"]), reverse=True
    )[:8]
    for row in timesheet_recent:
        row["hours_label"] = _fmt_hours(row["hours"])

    return _resp(
        request,
        "ui_dashboard.html",
        client,
        kpis=dict_to_ns(data.get("kpis", {})),
        recent_invoices=dict_to_ns(data.get("recent_invoices", [])),
        recent_transactions=dict_to_ns(data.get("recent_transactions", [])),
        last_sync=dict_to_ns(data.get("last_sync")) if data.get("last_sync") else None,
        top_suppliers=dict_to_ns(data.get("top_suppliers", [])),
        top_customers=dict_to_ns(data.get("top_customers", [])),
        monthly_finance=data.get("monthly_finance", []),
        timesheet_series=_timesheet_series(timesheet_entries),
        timesheet_recent=dict_to_ns(timesheet_recent),
    )


# ── Invoices ──────────────────────────────────────────────────────────────────


@router.get("/invoices")
def invoices_page(
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    payment_status: str | None = None,
    has_pdf: str | None = None,
    supplier_name: str | None = None,
):
    client = _client()
    rows = dict_to_ns(
        client.get_invoices(
            date_from=str(date_from) if date_from else None,
            date_to=str(date_to) if date_to else None,
            status=payment_status,
            has_pdf=has_pdf,
            supplier_name=supplier_name,
        )
    )
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
def invoice_files_page(request: Request, linked: str | None = None):
    client = _client()
    rows = dict_to_ns(client.get_invoice_files(linked=linked))
    return _resp(request, "invoice_files.html", client, rows=rows)


@router.get("/invoice-files/{file_id:int}/pdf")
def invoice_file_pdf(file_id: int):
    client = _client()
    try:
        upstream = client.get_invoice_file_pdf(file_id)
    except requests.RequestException:
        raise HTTPException(status_code=404, detail="PDF nem található") from None
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
        name=name,
        tax_id=tax_id or None,
        address=address or None,
        email=email or None,
        phone=phone or None,
        iban=iban or None,
        bban=bban or None,
    )
    rows = dict_to_ns(client.get_suppliers())
    summary = dict_to_ns(client.get_supplier_summary())
    return _resp(
        request, "suppliers.html", client, rows=rows, summary=summary, error=result.get("error")
    )


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
        supplier_id,
        name=name,
        tax_id=tax_id or None,
        address=address or None,
        email=email or None,
        phone=phone or None,
        iban=iban or None,
        bban=bban or None,
    )
    data = client.get_supplier(supplier_id)
    if not data:
        raise HTTPException(status_code=404, detail="Szállító nem található")
    return _resp(
        request,
        "supplier_detail.html",
        client,
        supplier=dict_to_ns(data),
        error=result.get("error"),
    )


@router.delete("/suppliers/{supplier_id:int}/delete")
def delete_supplier(request: Request, supplier_id: int):
    client = _client()
    result = client.delete_supplier(supplier_id)
    if result.get("error"):
        data = client.get_supplier(supplier_id)
        return _resp(
            request,
            "supplier_detail.html",
            client,
            supplier=dict_to_ns(data),
            error=result["error"],
        )
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
        name=name,
        tax_id=tax_id or None,
        address=address or None,
        email=email or None,
        phone=phone or None,
        payment_terms=int(payment_terms) if payment_terms else None,
        iban=iban or None,
        bban=bban or None,
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
        customer_id,
        name=name,
        tax_id=tax_id or None,
        address=address or None,
        email=email or None,
        phone=phone or None,
        payment_terms=int(payment_terms) if payment_terms else None,
        iban=iban or None,
        bban=bban or None,
    )
    data = client.get_customer(customer_id)
    if not data:
        raise HTTPException(status_code=404, detail="Vevő nem található")
    return _resp(
        request,
        "customer_detail.html",
        client,
        customer=dict_to_ns(data),
        error=result.get("error"),
    )


@router.delete("/customers/{customer_id:int}/delete")
def delete_customer(request: Request, customer_id: int):
    client = _client()
    result = client.delete_customer(customer_id)
    if result.get("error"):
        data = client.get_customer(customer_id)
        return _resp(
            request,
            "customer_detail.html",
            client,
            customer=dict_to_ns(data),
            error=result["error"],
        )
    return Response(status_code=200, headers={"HX-Redirect": "/ui/customers"})


# ── Transactions ──────────────────────────────────────────────────────────────


@router.get("/transactions")
def transactions_page(
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    linked: str | None = None,
    partner_name: str | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
):
    client = _client()
    rows = dict_to_ns(
        client.get_transactions(
            date_from=str(date_from) if date_from else None,
            date_to=str(date_to) if date_to else None,
            linked=linked,
            partner_name=partner_name,
            amount_min=amount_min,
            amount_max=amount_max,
        )
    )
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
    client.patch_invoice(invoice_id, label="Megjegyzés mentése", note=note)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(request, "invoice_detail.html", client, invoice=dict_to_ns(data))


@router.post("/invoices/{invoice_id}/fizetve")
def invoice_set_fizetve(request: Request, invoice_id: int, locked: str = Form("true")):
    client = _client()
    if locked == "true":
        client.patch_invoice(
            invoice_id, label="Fizetve jelölés", payment_status_locked=True, payment_status="PAID"
        )
    else:
        client.patch_invoice(invoice_id, label="Zár feloldása", payment_status_locked=False)
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
    return _resp(
        request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error")
    )


@router.post("/invoices/{invoice_id}/invoice-file/unlink")
def invoice_unlink_file(request: Request, invoice_id: int):
    client = _client()
    result = client.unlink_invoice_from_file(invoice_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(
        request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error")
    )


# ── Manual link / unlink (Invoice ↔ Supplier / Customer) ─────────────────────


@router.post("/invoices/{invoice_id}/supplier/link")
def invoice_link_supplier(request: Request, invoice_id: int, supplier_id: int = Form(...)):
    client = _client()
    result = client.link_invoice_supplier(invoice_id, supplier_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(
        request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error")
    )


@router.post("/invoices/{invoice_id}/supplier/unlink")
def invoice_unlink_supplier(request: Request, invoice_id: int):
    client = _client()
    result = client.unlink_invoice_supplier(invoice_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(
        request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error")
    )


@router.post("/invoices/{invoice_id}/customer/link")
def invoice_link_customer(request: Request, invoice_id: int, customer_id: int = Form(...)):
    client = _client()
    result = client.link_invoice_customer(invoice_id, customer_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(
        request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error")
    )


@router.post("/invoices/{invoice_id}/customer/unlink")
def invoice_unlink_customer(request: Request, invoice_id: int):
    client = _client()
    result = client.unlink_invoice_customer(invoice_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(
        request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error")
    )


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
        name=name,
        tax_id=tax_id or None,
        address=address or None,
        email=email or None,
        phone=phone or None,
        iban=iban or None,
        bban=bban or None,
    )
    if not result.get("error"):
        link_result = client.link_invoice_supplier(invoice_id, result["id"])
        result = {"error": link_result.get("error")} if link_result.get("error") else result
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(
        request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error")
    )


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
        name=name,
        tax_id=tax_id or None,
        address=address or None,
        email=email or None,
        phone=phone or None,
        payment_terms=int(payment_terms) if payment_terms else None,
        iban=iban or None,
        bban=bban or None,
    )
    if not result.get("error"):
        link_result = client.link_invoice_customer(invoice_id, result["id"])
        result = {"error": link_result.get("error")} if link_result.get("error") else result
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(
        request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error")
    )


# ── Manual link / unlink (BankTransaction ↔ InvoiceFile) ─────────────────────


@router.post("/transactions/{txn_id}/invoice-file/link")
def transaction_link_file(request: Request, txn_id: int, file_id: int = Form(...)):
    client = _client()
    result = client.link_transaction_to_file(txn_id, file_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(
        request,
        "partials/transaction_detail.html",
        client,
        tx=dict_to_ns(data),
        error=result.get("error"),
    )


@router.post("/transactions/{txn_id}/invoice-file/unlink")
def transaction_unlink_file(request: Request, txn_id: int):
    client = _client()
    result = client.unlink_transaction_from_file(txn_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(
        request,
        "partials/transaction_detail.html",
        client,
        tx=dict_to_ns(data),
        error=result.get("error"),
    )


# ── Manual link / unlink (BankTransaction ↔ Supplier / Customer) ─────────────


@router.post("/transactions/{txn_id}/supplier/link")
def transaction_link_supplier(request: Request, txn_id: int, supplier_id: int = Form(...)):
    client = _client()
    result = client.link_transaction_supplier(txn_id, supplier_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(
        request,
        "partials/transaction_detail.html",
        client,
        tx=dict_to_ns(data),
        error=result.get("error"),
    )


@router.post("/transactions/{txn_id}/supplier/unlink")
def transaction_unlink_supplier(request: Request, txn_id: int):
    client = _client()
    result = client.unlink_transaction_supplier(txn_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(
        request,
        "partials/transaction_detail.html",
        client,
        tx=dict_to_ns(data),
        error=result.get("error"),
    )


@router.post("/transactions/{txn_id}/customer/link")
def transaction_link_customer(request: Request, txn_id: int, customer_id: int = Form(...)):
    client = _client()
    result = client.link_transaction_customer(txn_id, customer_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(
        request,
        "partials/transaction_detail.html",
        client,
        tx=dict_to_ns(data),
        error=result.get("error"),
    )


@router.post("/transactions/{txn_id}/customer/unlink")
def transaction_unlink_customer(request: Request, txn_id: int):
    client = _client()
    result = client.unlink_transaction_customer(txn_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(
        request,
        "partials/transaction_detail.html",
        client,
        tx=dict_to_ns(data),
        error=result.get("error"),
    )


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
        name=name,
        tax_id=tax_id or None,
        address=address or None,
        email=email or None,
        phone=phone or None,
        iban=iban or None,
        bban=bban or None,
    )
    if not result.get("error"):
        link_result = client.link_transaction_supplier(txn_id, result["id"])
        result = {"error": link_result.get("error")} if link_result.get("error") else result
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(
        request,
        "partials/transaction_detail.html",
        client,
        tx=dict_to_ns(data),
        error=result.get("error"),
    )


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
        name=name,
        tax_id=tax_id or None,
        address=address or None,
        email=email or None,
        phone=phone or None,
        payment_terms=int(payment_terms) if payment_terms else None,
        iban=iban or None,
        bban=bban or None,
    )
    if not result.get("error"):
        link_result = client.link_transaction_customer(txn_id, result["id"])
        result = {"error": link_result.get("error")} if link_result.get("error") else result
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(
        request,
        "partials/transaction_detail.html",
        client,
        tx=dict_to_ns(data),
        error=result.get("error"),
    )


# ── Manual link / unlink (Invoice ↔ BankTransaction M2M) ─────────────────────


@router.post("/invoices/{invoice_id}/transactions/{txn_id}/link")
def invoice_link_transaction(request: Request, invoice_id: int, txn_id: int):
    client = _client()
    result = client.link_invoice_transaction(invoice_id, txn_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(
        request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error")
    )


@router.post("/invoices/{invoice_id}/transactions/{txn_id}/unlink")
def invoice_unlink_transaction(request: Request, invoice_id: int, txn_id: int):
    client = _client()
    result = client.unlink_invoice_transaction(invoice_id, txn_id)
    data = client.get_invoice(invoice_id)
    if not data:
        raise HTTPException(status_code=404, detail="Számla nem található")
    return _resp(
        request, "invoice_detail.html", client, invoice=dict_to_ns(data), error=result.get("error")
    )


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
    return _resp(
        request,
        "partials/transaction_detail.html",
        client,
        tx=dict_to_ns(data),
        error=result.get("error"),
    )


@router.post("/transactions/{txn_id}/invoices/{invoice_id}/unlink")
def transaction_unlink_invoice(request: Request, txn_id: int, invoice_id: int):
    client = _client()
    result = client.unlink_invoice_transaction(invoice_id, txn_id)
    data = client.get_transaction(txn_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tranzakció nem található")
    return _resp(
        request,
        "partials/transaction_detail.html",
        client,
        tx=dict_to_ns(data),
        error=result.get("error"),
    )


# ── Picker routes (HTMX-loaded candidate lists for modal) ─────────────────────


@router.get("/picker/invoice-files")
def picker_invoice_files(
    request: Request,
    source_type: str | None = None,
    source_id: int | None = None,
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
        request,
        "partials/picker_invoice_files.html",
        client,
        rows=rows,
        link_url_prefix=link_url_prefix,
        hx_target=hx_target,
        tx=tx,
        invoice=invoice,
    )


@router.get("/picker/transactions")
def picker_transactions(
    request: Request,
    invoice_id: int | None = None,
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
        request,
        "partials/picker_transactions.html",
        client,
        rows=rows,
        invoice_id=invoice_id,
        invoice=invoice,
    )


@router.get("/picker/invoices")
def picker_invoices(
    request: Request,
    txn_id: int | None = None,
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
        request,
        "partials/picker_invoices.html",
        client,
        rows=rows,
        txn_id=txn_id,
        tx=tx,
    )


@router.get("/picker/partners")
def picker_partners(
    request: Request,
    kind: str,
    source_type: str | None = None,
    source_id: int | None = None,
    invoice_id: int | None = None,
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
        request,
        "partials/picker_partners.html",
        client,
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
def dividend_page(request: Request, year: int | None = None):
    client = _client()
    effective_year = year or local_today().year
    report = dict_to_ns(client.get_dividend_report(year=effective_year))
    return _resp(request, "dividend.html", client, report=report, year=effective_year)


# ── Adók (tax payments) ───────────────────────────────────────────────────────


@router.get("/adok")
def adok_page(request: Request, year: int | None = None, saved: int = 0, error: str | None = None):
    client = _client()
    effective_year = year or local_today().year
    raw = client.get_tax_report(year=effective_year)
    report = dict_to_ns(raw)
    # totals_by_type and row.totals are dicts keyed by tax label strings with spaces/hyphens
    # ("NAV ÁFA", "HIPA - Késedelmi"); the template calls .get() which requires plain dicts.
    # dict_to_ns() converts them to SimpleNamespace, breaking .get() — restore them here.
    report.totals_by_type = raw.get("totals_by_type", {})
    for m, raw_m in zip(report.monthly or [], raw.get("monthly", []), strict=False):
        m.totals = raw_m.get("totals", {})

    raw_estimate = client.get_tax_estimate_report(year=effective_year)

    # "Becsült adók" is meant to look ahead only: drop any month before the
    # current one (already elapsed, regardless of whether it shows up in
    # "Havi bontás") and any month already shown in "Havi bontás" (actual tax
    # payments) above, so the two tables never repeat a month.
    current_month_key = local_today().strftime("%Y-%m")
    paid_months = {m.get("month") for m in raw.get("monthly", [])}
    upcoming = [
        m
        for m in raw_estimate.get("monthly", [])
        if m.get("month") >= current_month_key and m.get("month") not in paid_months
    ]
    raw_estimate["monthly"] = upcoming
    # "Becsült bevétel" starts from a fixed monthly assumption rather than a
    # trend-based projection — recompute every tax figure for each upcoming
    # month from this fixed gross revenue (mirroring invoice-core's
    # tax_service._tax_row formula) instead of only overriding the display
    # column, so all rows in the table become internally consistent rather
    # than mixing real/averaged invoice data with a fixed income figure. This
    # is only the server-rendered starting point — the template makes the
    # "Becsült bevétel" cell an editable input per row and recomputes every
    # other cell in that row client-side (adok.html's scripts block) whenever
    # the user changes it, so JS is the source of truth after first paint.
    # No expense data applies to a fixed-income assumption, so expenses are
    # taken as 0; the standard Hungarian 27% VAT rate splits the fixed gross
    # figure into net revenue + VAT payable (no input-VAT credit assumed).
    fixed_monthly_income = 2_500_000.0
    vat_rate = 0.27
    tao_rate = raw_estimate.get("tao_rate", 0.10)
    hipa_rate = raw_estimate.get("hipa_rate", 0.02)

    # Saved per-month overrides win over the 2.5M fallback assumption; if the
    # overrides call fails (e.g. endpoint not up yet), overrides_by_month
    # stays empty and every month silently falls back to the fixed default —
    # the page must still render.
    overrides_raw = client.get_tax_estimate_overrides(year=effective_year) or {}
    overrides_by_month = {
        o.get("month"): o.get("gross_revenue")
        for o in overrides_raw.get("months", [])
        if o.get("month") is not None
    }

    for m in upcoming:
        month_int = int(m["month"].split("-")[1])
        gross_revenue = overrides_by_month.get(month_int, fixed_monthly_income)
        net_revenue = gross_revenue / (1 + vat_rate)
        vat_payable = gross_revenue - net_revenue
        # HIPA (helyi iparűzési adó) is a deductible business expense for
        # Hungarian corporate income tax purposes, so it must reduce the TAO
        # base — computing TAO on the pre-HIPA profit overstates the
        # liability. This table only models company-level taxes (ÁFA, TAO/
        # KIVA, HIPA); personal-level SZJA/SZOCHÓ on an eventual dividend
        # payout are a separate, discretionary decision covered in detail by
        # the Fizetés Calculator, not an automatic company obligation.
        hipa_tax = max(0.0, net_revenue * hipa_rate)
        tao_base = net_revenue - hipa_tax
        tao_tax = max(0.0, tao_base * tao_rate)
        m["gross_revenue"] = gross_revenue
        m["revenue"] = net_revenue
        m["expenses"] = 0.0
        m["vat_payable"] = vat_payable
        m["tao_tax"] = tao_tax
        m["hipa_tax"] = hipa_tax
        m["total"] = vat_payable + tao_tax + hipa_tax
    estimate_fields = [
        "revenue",
        "gross_revenue",
        "expenses",
        "vat_payable",
        "tao_tax",
        "hipa_tax",
        "total",
    ]
    raw_estimate["totals"] = {
        "month": "Összesen",
        "is_projected": False,
        **{f: sum(m.get(f, 0) for m in upcoming) for f in estimate_fields},
    }

    # "Becsült adók" only ever shows company-level tax types: ÁFA, TAO/KIVA and
    # HIPA. NAV SZJA and NAV Szochó are personal-level taxes on an eventual
    # dividend payout, not an automatic company obligation, so they're left
    # out here (the Fizetés Calculator models that layer instead); "HIPA -
    # Késedelmi" / "Iparkamara" have no estimate formula at all. Excluding all
    # of these from estimate_label_map means none of them can ever become a
    # column, regardless of whether they show up as an active tax type in
    # "Havi bontás".
    estimate_label_map = {
        "NAV ÁFA": "vat_payable",
        "NAV TAO": "tao_tax",
        "HIPA": "hipa_tax",
    }
    active_labels = [
        label
        for label in report.tax_labels
        if label in estimate_label_map and report.totals_by_type.get(label, 0)
    ]
    if not active_labels:
        # No tax paid yet this year (e.g. early in a fresh year) — fall back to
        # showing every estimable tax type instead of an empty table, so the
        # projection is still useful before any actual payment history exists.
        active_labels = [label for label in report.tax_labels if label in estimate_label_map]
    for m in upcoming:
        m["label_totals"] = {
            label: m.get(estimate_label_map[label], 0.0)
            for label in active_labels
            if label in estimate_label_map
        }
    raw_estimate["totals"]["label_totals"] = {
        label: raw_estimate["totals"].get(estimate_label_map[label], 0.0)
        for label in active_labels
        if label in estimate_label_map
    }

    estimate = dict_to_ns(raw_estimate)
    for m, raw_m in zip(estimate.monthly or [], upcoming, strict=False):
        m.label_totals = raw_m.get("label_totals", {})
    estimate.totals.label_totals = raw_estimate["totals"].get("label_totals", {})
    return _resp(
        request,
        "adok.html",
        client,
        report=report,
        estimate=estimate,
        estimate_labels=active_labels,
        year=effective_year,
        saved=saved,
        error=error,
    )


@router.post("/adok/estimate")
def adok_save_estimate(
    request: Request,
    year: int = Form(...),
    month: list[int] = Form([]),
    gross_revenue: list[float] = Form([]),
):
    client = _client()
    months = [
        {"month": mth, "gross_revenue": rev} for mth, rev in zip(month, gross_revenue, strict=False)
    ]
    result = client.save_tax_estimate_overrides(year, months)
    if result.get("error"):
        return RedirectResponse(
            url=f"/ui/adok?year={year}&error={quote(result['error'])}", status_code=303
        )
    return RedirectResponse(url=f"/ui/adok?year={year}&saved=1", status_code=303)


# ── Fizetés Calculator (wage vs. dividend optimizer) ──────────────────────────


@router.get("/fizetes-kalkulator")
def fizetes_kalkulator_page(request: Request):
    client = _client()
    return _resp(request, "fizetes_kalkulator.html", client)


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
    date_from: str | None = Form(None),
    date_to: str | None = Form(None),
    sync_mode: str | None = Form("full"),
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
