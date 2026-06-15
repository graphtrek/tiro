"""Pydantic models for NAV Online Számla data."""

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ───────────────────────────────────────────────

class InvoiceType(str, Enum):
    """Számlatípusok."""
    SML = "SML"           # Számla
    ELSZ = "ELSZ"         # Előlegszámla
    SVO = "SVO"           # Számla módosító
    EHO = "EHO"           # Előlegszámla módosító
    KNY = "KNY"           # Könyvelési bizonylat


class InvoiceStatus(str, Enum):
    """Számla státusz."""
    BEJELENTVE = "BEJELENTVE"
    MÓDOSÍTVA = "MÓDOSÍTVA"
    VISSZAVONT = "VISSZAVONT"


# ── Invoice models ─────────────────────────────────────

class InvoiceLineItem(BaseModel):
    """Számla sor (line item)."""

    tétel_leiras: str = ""
    mennyiseg: float = 0.0
    egysagar: float = 0.0
    adomertek: float = 0.0
    ado_kulcs: int = 27  # ÁFA kulcs (5, 18, 27)


class InvoiceHeader(BaseModel):
    """Számla fejléc."""

    szamlaszam: str = Field(..., description="Számla egyedi azonosító")
    szamlatipus: InvoiceType = InvoiceType.SML
    keltes_datuma: date
    szamlazas_vegezo: str  # Számlázó neve / adószáma
    vevo_adoszama: str = ""  # Vevő adószáma
    vevo_neve: str = ""  # Vevő megnevezése
    vevo_cime: str = ""  # Vevő címe
    szamlatipus_sorszam: int = 1
    szamlasorszar: str = ""

    # Összesítők
    bruttototal: float = 0.0
    netto_total: float = 0.0
    ado_total: float = 0.0


class InvoiceDetail(BaseModel):
    """Teljes számla adat (fejléc + tételek)."""

    header: InvoiceHeader
    line_items: list[InvoiceLineItem] = []
    status: Optional[InvoiceStatus] = None
    keltes_datuma: date


class InvoiceListEntry(BaseModel):
    """Rövidített számla lista elem."""

    szamlaszam: str
    szamlatipus: InvoiceType
    keltes_datuma: date
    szamlazo_neve: str = ""
    vevo_adoszama: str = ""
    bruttototal: float = 0.0
    status: Optional[InvoiceStatus] = None


# ── Authentication models ───────────────────────────────

class AuthRequest(BaseModel):
    """Bejelentkezési kérés."""

    username: str
    password: str
    license_key: str


class AuthResponse(BaseModel):
    """Bejelentkezési válasz."""

    session_id: str = ""
    success: bool = False
    message: str = ""


# ── Query models ───────────────────────────────────────

class InvoiceQueryParams(BaseModel):
    """Lekérdezési paraméterek."""

    from_date: Optional[date] = None
    to_date: Optional[date] = None
    invoice_type: Optional[InvoiceType] = None
    szamlaszam: Optional[str] = None
    status: Optional[InvoiceStatus] = None
    szamlazo_adoszam: Optional[str] = None


class InvoiceQueryResponse(BaseModel):
    """Lekérdezési válasz."""

    invoices: list[InvoiceListEntry] = []
    total_count: int = 0


# ── Reporting models ───────────────────────────────────

class SubmitInvoiceRequest(BaseModel):
    """Adatszolgáltatási kérés."""

    invoice: InvoiceDetail


class SubmitInvoiceResponse(BaseModel):
    """Adatszolgáltatási válasz."""

    success: bool = False
    message: str = ""
    submission_id: str = ""


# ── NAV Online Számla 3.0 — real API models ─────────────

class InvoiceDirection(str, Enum):
    """Lekérdezés iránya."""
    OUTBOUND = "OUTBOUND"   # kiállított (eladó oldal)
    INBOUND = "INBOUND"     # befogadott (vevő oldal)


class ManageInvoiceOperation(str, Enum):
    """manageInvoice művelet típusa."""
    CREATE = "CREATE"
    MODIFY = "MODIFY"
    STORNO = "STORNO"


class InvoiceDigest(BaseModel):
    """Egy ``invoiceDigest`` lista elem a queryInvoiceDigest válaszból."""

    invoice_number: str = ""
    invoice_operation: str = ""
    invoice_category: str = ""
    invoice_issue_date: str = ""
    supplier_tax_number: str = ""
    supplier_name: str = ""
    customer_tax_number: str = ""
    customer_name: str = ""
    invoice_net_amount: Optional[float] = None
    invoice_vat_amount: Optional[float] = None
    currency: str = ""
    ins_date: str = ""


class DigestQueryParams(BaseModel):
    """queryInvoiceDigest paraméterek (kötelező dátumtartomány)."""

    from_date: date
    to_date: date
    direction: InvoiceDirection = InvoiceDirection.OUTBOUND
    page: int = 1


class TokenExchangeResult(BaseModel):
    """tokenExchange eredménye."""

    token: str = ""
    valid_from: str = ""
    valid_to: str = ""


class TransactionResult(BaseModel):
    """manageInvoice / queryTransactionStatus eredménye."""

    transaction_id: str = ""
    success: bool = False
    message: str = ""