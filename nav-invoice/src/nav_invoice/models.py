"""Pydantic models for NAV Online Számla data."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

# ── Enums ───────────────────────────────────────────────

class InvoiceType(StrEnum):
    """Számlatípusok."""
    SML = "SML"           # Számla
    ELSZ = "ELSZ"         # Előlegszámla
    SVO = "SVO"           # Számla módosító
    EHO = "EHO"           # Előlegszámla módosító
    KNY = "KNY"           # Könyvelési bizonylat


class InvoiceStatus(StrEnum):
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
    status: InvoiceStatus | None = None


class InvoiceListEntry(BaseModel):
    """Rövidített számla lista elem."""

    szamlaszam: str
    szamlatipus: InvoiceType
    keltes_datuma: date
    szamlazo_neve: str = ""
    vevo_adoszama: str = ""
    bruttototal: float = 0.0
    status: InvoiceStatus | None = None


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

    from_date: date | None = None
    to_date: date | None = None
    invoice_type: InvoiceType | None = None
    szamlaszam: str | None = None
    status: InvoiceStatus | None = None
    szamlazo_adoszam: str | None = None


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

class InvoiceDirection(StrEnum):
    """Lekérdezés iránya."""
    OUTBOUND = "OUTBOUND"   # kiállított (eladó oldal)
    INBOUND = "INBOUND"     # befogadott (vevő oldal)


class ManageInvoiceOperation(StrEnum):
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
    invoice_net_amount: float | None = None
    invoice_vat_amount: float | None = None
    currency: str = ""
    ins_date: str = ""


class DigestQueryParams(BaseModel):
    """queryInvoiceDigest paraméterek (kötelező dátumtartomány)."""

    from_date: date
    to_date: date
    direction: InvoiceDirection = InvoiceDirection.OUTBOUND
    page: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_date_range(self) -> "DigestQueryParams":
        if self.to_date < self.from_date:
            raise ValueError("to_date must be >= from_date")
        if (self.to_date - self.from_date).days > 35:
            raise ValueError("Date range cannot exceed 35 days (NAV limit)")
        return self


class InvoiceLineData(BaseModel):
    """Egy tételsor a queryInvoiceData válasz invoiceLines/line eleméből."""

    line_number: str = ""
    line_description: str = ""
    quantity: float | None = None
    unit_of_measure: str = ""
    unit_price: float | None = None
    line_net_amount: float | None = None
    line_vat_rate: float | None = None  # vatPercentage tizedes törtként, pl. 0.27
    line_vat_amount: float | None = None
    line_gross_amount: float | None = None


class InvoiceVatSummaryData(BaseModel):
    """ÁFA-kulcsonkénti összesítő az invoiceSummary/summaryNormal/summaryByVatRate elemekből."""

    vat_rate: float | None = None
    vat_rate_net_amount: float | None = None
    vat_rate_vat_amount: float | None = None


class InvoiceDetailData(BaseModel):
    """A teljes queryInvoiceData XML-ből kinyert mezők.

    A digestből nem elérhető adatok: cím, bankszámla, fizetési mód/határidő,
    fejléc-kiegészítők (kategória, teljesítés dátuma, pénznem, árfolyam,
    megjelenés), tételsorok és ÁFA-kulcsonkénti összesítők.
    """

    invoice_number: str = ""
    supplier_address: str = ""
    supplier_bank_account: str = ""
    customer_address: str = ""
    customer_bank_account: str = ""
    payment_method: str = ""
    payment_due_date: str = ""
    # invoiceDetail blokkból — más forrás, mint InvoiceDigest.invoice_category
    invoice_category: str = ""
    delivery_date: str = ""  # invoiceDeliveryDate
    currency_code: str = ""  # currencyCode
    exchange_rate: float | None = None
    invoice_appearance: str = ""
    invoice_net_amount: float | None = None
    invoice_vat_amount: float | None = None
    invoice_gross_amount: float | None = None
    lines: list[InvoiceLineData] = []
    vat_summary: list[InvoiceVatSummaryData] = []


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