"""Server-side anonymization for the "open, anonymized read-only" JWT tier.

Wired via the `anonymized: bool` JWT claim issued by the `auth` service
(alongside the existing `role` claim). `role == "read_only"` alone is
*not* sufficient — the trusted `READONLY_EMAILS`/`READONLY_DOMAINS` tier is
also `read_only` but must keep seeing real data; only sessions whose token
carries `anonymized: true` get masked data. See
`doc/`-adjacent design doc discussed with the user for the full
rationale (any verified Google login is now allowed in, but the unknown/open
tier must not see real partner names or real financial figures).

Every primitive here is deterministic (same real input -> same fake output,
every time, across requests and across process restarts) so that a masked
value stays visually consistent for a given viewer as they browse multiple
pages, while still reading as a plausible business name/amount/identifier
rather than an obvious hash string.
"""

from __future__ import annotations

import hashlib
import re

from fastapi import Request

# ── Recognized payload key sets (module-level constants, reused by anonymize()) ──

NAME_KEYS = {
    "name",
    "supplier_name",
    "customer_name",
    "partner_name",
    "counterparty_name",
}

# `user_name`/`owner_name` hold a real person's name (a company employee),
# not a business/company name -- masked with `fake_person_name` (Hungarian
# given+family name) instead of `fake_name` (Hungarian company name), so the
# anonymized value still reads as the right kind of entity.
PERSON_NAME_KEYS = {"user_name", "owner_name"}

# Handled separately from NAME_KEYS because its value is a list of strings
# (or, in this codebase, a comma-separated string of alternate names) rather
# than a single name.
KNOWN_NAMES_KEY = "known_names"

IDENTIFIER_KEYS = {
    "tax_id",
    "iban",
    "bban",
    "email",
    "phone",
    "address",
    "counterparty_account",
    "counterparty_iban",
    "counterparty_address",
    "sender_address",
    "invoice_number",
    "linked_invoice_number",
    "code",
    "project_code",
    "transaction_id",
    "counterparty_bank_code",
    "card_last_four",
    "invoice_file_filename",
    "filename",
    "supplier_tax_id",
    "customer_tax_id",
    "supplier_tax_number",
    "customer_tax_number",
    "supplier_address",
    "customer_address",
    "supplier_bank_account",
    "customer_bank_account",
    "bank_transaction_id",
    "bank_txn_external_id",
    "short_name",
    "goal",
    "deliverable",
}

# `words` is the PDF's full extracted text (pdfplumber/OCR output --
# effectively the entire real invoice content as plain text); no field-level
# fake generator can meaningfully stand in for a real document's full text,
# so it's blanked outright for the anonymized tier.
_REDACT_KEYS = {"words"}

# `preview_base64` (invoice-files list) / `invoice_file_preview_base64`
# (invoices list, transactions list -- same image, different field name per
# endpoint) is a rendered thumbnail of the real PDF page. Unlike `words`,
# leaving this blank was a visibly broken/empty preview in the UI, so it's
# replaced with one shared, static "generic invoice document" placeholder
# image instead -- not a per-file fake (there's no meaningful way to
# synthesize a unique fake page image per invoice), just a fixed stand-in
# that reads as "a PDF preview" without showing any real content.
_FAKE_PREVIEW_KEYS = {"preview_base64", "invoice_file_preview_base64"}

_FAKE_PDF_PREVIEW_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAPAAAAFACAIAAAANimYEAAADjklEQVR42u3dMa6kMBBFUdbJEr2O"
    "DojZCyLtCAkRAoVc5fN04wk8R+jL36OZluUnlWlyBAJaAlr6GPS+b1K6gBbQEtAS0BLQAhpoAS0B"
    "LQEtAS2ggRbQEtAS0BLQAhpoAS0BLQEtxYOeyw0OoIEW0EC/Vys3oIEGGmiggQYaaKCBBhpooIEG"
    "2rWdazuggQYaaAENtIAGWkADDTTQru16vpgDGmiggQYaaKCBBhpooIEGGmj/SFau7SSgJaAloCWg"
    "BbQEtAS0BLQEtICWgJaAloCWgBbQEtAS0BLQAhpoAS0BLQEtAS2ggRbQR6tZZwPagAbagDYD2gxo"
    "AxpoAxpoqwVa8ptCCWgJaAHtdAS05LWdneec3UMDbUADDbSDBhpoAxpooJ0z0EAb0EADLflNoQS0"
    "BLSABlpAS17buYl7lqMDGmiggQYaaAMaaH8rzhlooB0d0EAD7aCBHhW05DeFEtAS0ALa6QhoCWgJ"
    "aAloAS0BLQEtAS0BLaAloCWgJaAloAW0BLQEtAS0gAZaQEtAS0BLQAtooAW0BLQEtAS0gAZaQF//"
    "IOmtgBbQfuSQHzkkoCWgJaAFNNACWgJaAloCWkDfA93MAga0AQ20AQ20AW0GtAENtAENtAENtAFt"
    "BrQBDbQB7XGSPE6SgJaAloAW0E5HI4NezQIGtAENtAENtAFtBrQBDbQBDbQBDbQBbdY7aMlbDqlX"
    "0P6LSPmPNyU/ckhAC2jXduYe2gxoM6ANaKANaKANaDOgzYA2oIE2oCVvOSTvoSXvoSWgBbTkPbSZ"
    "e2gzoA1ooA1ooA1oM6ANaKANaKANaKCtKmjJWw7Je2h5D+0LLV9opyOgJe+hzdxDG9BAG9BAG9Bm"
    "QJsBbUADbUADbUCbZQUtecsheQ8t76F9oeUL7XQEtOQ9tJl7aAMaaAMaaAPaDGgzoA1ooA1ooA1o"
    "s6ygJW85JO+h5T20L7R8oZ2OgJa8hzZzD21AA21AA21AmwFtBrQBDbQBDbQBbZYVtOQth+Q9tLyH"
    "9oWWL7TTEdAS0BLQEtACWgJaUbXBBjTQQAMNNNACGmgBDbSABhpooIEGGmgBDbSABloCWkADLaAl"
    "oCWgJaDrNA82oIEGGmiggRbQQAtooAU00EADDTTQQAtooAU00AIaaKCBBloeJ0lAS0BLQAtopyOg"
    "JaAloCWgBbQEtAS0BLQEtICWgJaAliJAS9kDWkBLQEsf9AevUmfL9ALRqwAAAABJRU5ErkJggg=="
)

# Plural/list-valued counterparts of an IDENTIFIER_KEYS entry -- value is a
# list of strings, each masked individually with the same `kind` as its
# singular sibling (so e.g. "INV-1" masks identically whether it shows up as
# a lone `invoice_number` or inside an `invoice_numbers` list).
_LIST_IDENTIFIER_KEYS = {
    "invoice_numbers": "invoice_number",
    "bank_transaction_ids": "bank_transaction_id",
}

AMOUNT_KEYS = {
    "amount",
    "amount_total",
    "amount_net",
    "amount_vat",
    "total",
    "unpaid_amount",
    "income",
    "expense",
    "expenses",
    "fees",
    "invoice_income",
    "invoice_expense",
    "invoice_total",
    "bank_total",
    "balance",
    "revenue",
    "gross_revenue",
    "gross_profit",
    "row_total",
    "grand_total",
    "net_profit",
    "net_dividend_without_szocho",
    "net_dividend_with_szocho",
    "vat_payable",
    "tao_tax",
    "hipa_tax",
    "szja_tax",
    "szocho_tax",
    "invoice_net_amount",
    "invoice_vat_amount",
    "invoice_gross_amount",
    "unit_price",
    "line_net_amount",
    "line_vat_amount",
    "line_gross_amount",
    "vat_rate_net_amount",
    "vat_rate_vat_amount",
    "bank_amount",
    "net_wage",
}

# dict[str, float] fields keyed by an arbitrary label (e.g. a tax type name)
# rather than by a recognized amount key -- every value in the dict is still
# a monetary figure and must be scaled the same way as a plain AMOUNT_KEYS
# field would be.
AMOUNT_DICT_KEYS = {
    "totals_by_type",
    "totals",
}

# Fields that, when found alongside amount-only rows with no partner in
# scope, can still be used to derive a stable (if not partner-specific)
# scale key -- e.g. a bare monthly-aggregate row.
_CONTEXT_FALLBACK_KEYS = ("month",)

_UNSCOPED_KEY = "unscoped"

_ADJECTIVES = [
    "Kobalt",
    "Zafir",
    "Rubin",
    "Ezust",
    "Arany",
    "Kristaly",
    "Gránit",
    "Borostyán",
    "Onix",
    "Turmalin",
    "Smaragd",
    "Titán",
    "Platina",
    "Opál",
    "Jáde",
    "Korall",
]

_NOUNS = [
    "Trading",
    "Consulting",
    "Solutions",
    "Logistics",
    "Systems",
    "Partners",
    "Ventures",
    "Holding",
    "Services",
    "Industries",
    "Networks",
    "Dynamics",
    "Global",
    "Group",
    "Works",
    "Labs",
]

_SUFFIXES = ["Kft.", "Zrt.", "Bt.", "Nyrt."]

_FAMILY_NAMES = [
    "Kovács",
    "Szabó",
    "Nagy",
    "Tóth",
    "Horváth",
    "Varga",
    "Kiss",
    "Molnár",
    "Németh",
    "Farkas",
    "Balogh",
    "Papp",
    "Takács",
    "Juhász",
    "Lakatos",
    "Fekete",
]

_GIVEN_NAMES = [
    "János",
    "Péter",
    "László",
    "Zoltán",
    "Gábor",
    "Katalin",
    "Éva",
    "Anna",
    "Zsuzsanna",
    "Judit",
    "Attila",
    "Sándor",
    "Csilla",
    "Andrea",
    "Márta",
    "Tamás",
]


def should_anonymize(request: Request) -> bool:
    """True only for the "open read-only, anonymized" tier.

    Deliberately not keyed off `role == "read_only"` alone -- the trusted
    `READONLY_EMAILS`/`READONLY_DOMAINS` tier is also `read_only` but must
    keep seeing real data. Only a token whose `anonymized` claim is
    literally `True` triggers masking.
    """
    user = getattr(request.state, "user", None)
    if not user:
        return False
    return user.get("anonymized") is True


def _digest_bytes(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def fake_name(real: str | None) -> str | None:
    """Deterministic pseudonym that reads like a plausible company name."""
    if not real:
        return real
    digest = _digest_bytes(real.strip().lower())
    adjective = _ADJECTIVES[digest[0] % len(_ADJECTIVES)]
    noun = _NOUNS[digest[1] % len(_NOUNS)]
    suffix = _SUFFIXES[digest[2] % len(_SUFFIXES)]
    return f"{adjective} {noun} {suffix}"


def fake_person_name(real: str | None) -> str | None:
    """Deterministic pseudonym that reads like a real person's name
    (Hungarian family-name-first order, e.g. "Kovács János") -- distinct
    from `fake_name`'s company-style output, for fields that hold an
    employee's name (e.g. `user_name`) rather than a business's."""
    if not real:
        return real
    digest = _digest_bytes(real.strip().lower())
    family = _FAMILY_NAMES[digest[0] % len(_FAMILY_NAMES)]
    given = _GIVEN_NAMES[digest[1] % len(_GIVEN_NAMES)]
    return f"{family} {given}"


def fake_amount(real: float | None, key: str) -> float | None:
    """Scale `real` by a deterministic pseudo-random factor in ~[0.5, 2.0).

    The factor is derived from `key` (a stable entity identifier), NOT from
    `real` itself, so every amount belonging to the same partner/entity
    scales by the exact same factor -- relative proportions (e.g. sum of a
    supplier's invoices vs. its displayed total) stay internally plausible.
    """
    if real is None:
        return None
    if real == 0.0:
        return 0.0
    factor = int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16) % 1500 / 1000 + 0.5
    return round(real * factor, 2)



# Different field names that hold the same *kind* of real-world value must
# hash to the same fake output for the same input (e.g. an invoice number
# shown via `invoice_number` on one page and `linked_invoice_number` on
# another must mask identically) -- canonicalize before hashing.
_KIND_ALIASES = {
    "linked_invoice_number": "invoice_number",
    "project_code": "code",
    "counterparty_iban": "iban",
    "filename": "invoice_file_filename",
    "supplier_tax_id": "tax_id",
    "customer_tax_id": "tax_id",
    "supplier_tax_number": "tax_id",
    "customer_tax_number": "tax_id",
    "supplier_address": "address",
    "customer_address": "address",
    "supplier_bank_account": "bban",
    "customer_bank_account": "bban",
    "bank_transaction_id": "transaction_id",
    "bank_txn_external_id": "transaction_id",
}


def fake_identifier(real: str | None, kind: str) -> str | None:
    """Deterministic hash-based fake value, formatted plausibly for `kind`."""
    if not real:
        return real
    kind = _KIND_ALIASES.get(kind, kind)
    digest = hashlib.sha256(f"{kind}:{real.strip().lower()}".encode()).hexdigest()
    if kind == "tax_id":
        return str(int(digest[:8], 16) % 100_000_000).zfill(8)
    if kind == "iban":
        return "HU" + str(int(digest[:24], 16) % (10**26)).zfill(26)
    if kind == "bban":
        return str(int(digest[:16], 16) % (10**16)).zfill(16)
    if kind == "email":
        return f"fake{digest[:8]}@example.invalid"
    if kind == "phone":
        return "+36" + str(int(digest[:9], 16) % (10**9)).zfill(9)
    if kind == "invoice_number":
        # NAV-style: 4 uppercase letters + 9 digits (e.g. "AHUW261564234").
        letters = "".join(chr(65 + digest_byte % 26) for digest_byte in bytes.fromhex(digest[:8]))
        digits = str(int(digest[8:20], 16) % (10**9)).zfill(9)
        return f"{letters}{digits}"
    if kind == "code":
        # Matches project_service._compose_code's "{short_name}-{seq:03d}"
        # shape (e.g. "ACME-001") without revealing the real short name.
        word = _NOUNS[int(digest[:2], 16) % len(_NOUNS)].upper()
        seq = int(digest[2:6], 16) % 1000
        return f"{word}-{seq:03d}"
    if kind == "short_name":
        # A project's raw "Azonosító / rövid név" (e.g. "FVM") -- the source
        # material `code` is composed from (`_compose_code`); masked
        # independently (own hash namespace) rather than aliased to `code`,
        # since the real value is just the bare abbreviation, not the full
        # "WORD-NNN" shape.
        return _ADJECTIVES[int(digest[:2], 16) % len(_ADJECTIVES)][:3].upper()
    if kind == "transaction_id":
        return digest[:20].upper()
    if kind == "counterparty_bank_code":
        return str(int(digest[:4], 16) % 900 + 100)
    if kind == "card_last_four":
        return str(int(digest[:4], 16) % 10_000).zfill(4)
    if kind == "invoice_file_filename":
        return _fake_filename(real, digest)
    # address, counterparty_account, counterparty_address, sender_address, ...
    return f"Fake utca {int(digest[:4], 16) % 999 + 1}., {digest[:6]}"


_FILENAME_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}_\d+_)(.+?)(\.[A-Za-z0-9]+)?$")


def _fake_filename(real: str, digest: str) -> str:
    """Downloaded invoice PDFs are named `YYYY-MM-DD_NNNN_<sanitized>.pdf`
    (see attachment-downloader) -- the date/counter prefix isn't identifying,
    but `<sanitized>` is usually derived from the real email subject/sender
    and can spell out a supplier name or invoice number. Keep the prefix and
    extension (harmless, useful for sorting/recognizing filetype) and replace
    only the sanitized portion."""
    match = _FILENAME_PREFIX_RE.match(real)
    word = _NOUNS[int(digest[:2], 16) % len(_NOUNS)]
    suffix = digest[2:8]
    if match:
        prefix, _, ext = match.groups()
        return f"{prefix}{word}_{suffix}{ext or ''}"
    return f"{word}_{suffix}"


# `description`/`payment_reference` are free text -- masked only when the
# enclosing dict also looks like a bank-transaction row (has a `bank` or
# `transaction_id` sibling key) or a timesheet-entry row (has an `hours`
# sibling key), since the SAME `description` key name is reused by multiple
# unrelated DTOs (bank narrative vs. timesheet work-log note) that each need
# a different fake generator -- and reused as a *different, non-financial*
# kind of text by others still (e.g. an activity type's own description),
# which must NOT be scrambled at all.
_TRANSACTION_TEXT_KEYS = {"description", "payment_reference"}

# `line_description` ("Megnevezés" on an invoice's line items) is a unique
# key name (not reused elsewhere in the codebase) so it's always masked
# unconditionally, no sibling-key context check needed like the
# `description`/`payment_reference` pair above.
_UNCONDITIONAL_TEXT_KEYS = {"line_description"}

_FAKE_DESCRIPTIONS = [
    "Szállítói számla kiegyenlítés",
    "Szolgáltatási díj átutalása",
    "Beszerzés ellenértéke",
    "Havi díj átutalás",
    "Partner részére átutalás",
    "Számla ellenérték",
    "Megrendelés kiegyenlítése",
    "Teljesítés díja",
]

_FAKE_WORK_DESCRIPTIONS = [
    "Fejlesztési feladatok",
    "Kód review és tesztelés",
    "Ügyfél egyeztetés",
    "Dokumentáció készítése",
    "Tervezési megbeszélés",
    "Hibajavítás",
    "Rendszerkarbantartás",
    "Projektmenedzsment feladatok",
]

_FAKE_VACATION_NOTES = [
    "Éves szabadság",
    "Táv-munka",
    "Orvosi vizsgálat",
    "Családi program",
    "Egyéb elfoglaltság",
]


def _looks_like_transaction_row(node: dict) -> bool:
    return "bank" in node or "transaction_id" in node


def _looks_like_timesheet_row(node: dict) -> bool:
    return "hours" in node


def _looks_like_invoice_row(node: dict) -> bool:
    return "invoice_number" in node


def _looks_like_vacation_row(node: dict) -> bool:
    return "start_date" in node and "end_date" in node


def fake_transaction_text(real: str | None, kind: str) -> str | None:
    """Deterministic fake narrative for a bank transaction's free-text
    `description`/`payment_reference`/`note`, an invoice's `note`, a
    timesheet entry's `description` (work-log note), or a vacation
    request's `note` -- real narratives often spell out a counterparty/
    person name or invoice number in plain text, which no field-level mask
    can catch, so these are replaced outright rather than partially
    scrubbed."""
    if not real:
        return real
    digest = hashlib.sha256(f"{kind}:{real.strip().lower()}".encode()).hexdigest()
    if kind in ("description", "line_description", "note"):
        return _FAKE_DESCRIPTIONS[int(digest[:2], 16) % len(_FAKE_DESCRIPTIONS)]
    if kind == "work_description":
        return _FAKE_WORK_DESCRIPTIONS[int(digest[:2], 16) % len(_FAKE_WORK_DESCRIPTIONS)]
    if kind == "vacation_note":
        return _FAKE_VACATION_NOTES[int(digest[:2], 16) % len(_FAKE_VACATION_NOTES)]
    # payment_reference
    return f"REF-{digest[:10].upper()}"


def _fake_known_names(real):
    """`known_names` holds either a list of alternate names or (this
    codebase's actual shape) a single comma-separated string of them."""
    if real is None:
        return None
    if isinstance(real, list):
        return [fake_name(v) if isinstance(v, str) else v for v in real]
    if isinstance(real, str):
        if not real.strip():
            return real
        parts = [p.strip() for p in real.split(",")]
        return ", ".join(fake_name(p) for p in parts if p)
    return real


# `participants` ("Résztvevők" on a timesheet entry) is a comma-separated
# list of real person names (e.g. "Kozma Zoltán, Erős Péter") -- a unique key
# name (not reused elsewhere), always masked unconditionally, one
# `fake_person_name` per comma-separated name.
PARTICIPANTS_KEY = "participants"


def _fake_participants(real):
    if real is None:
        return None
    if not isinstance(real, str):
        return real
    if not real.strip():
        return real
    parts = [p.strip() for p in real.split(",")]
    return ", ".join(fake_person_name(p) for p in parts if p)


# `bank_accounts` ("Ismert bankszámlák" on a supplier/customer detail page)
# is a comma-separated history of every bank account number ever seen for
# that partner (service.py's `_record_partner_bank_account`) -- a unique key
# name, always masked unconditionally, one `bban`-style fake identifier per
# comma-separated account.
BANK_ACCOUNTS_KEY = "bank_accounts"


def _fake_bank_accounts(real):
    if real is None:
        return None
    if not isinstance(real, str):
        return real
    if not real.strip():
        return real
    parts = [p.strip() for p in real.split(",")]
    return ",".join(fake_identifier(p, "bban") for p in parts if p)


def _derive_scale_key(node: dict) -> str | None:
    """Prefer `tax_id` over a name field if both are present in this dict."""
    tax_id = node.get("tax_id")
    if tax_id:
        return f"tax_id:{tax_id}"
    for key in ("name", "supplier_name", "customer_name", "partner_name", "counterparty_name"):
        value = node.get(key)
        if value:
            return f"name:{value}"
    return None


def _anonymize_node(node, scale_key: str | None):
    if isinstance(node, dict):
        local_key = _derive_scale_key(node)
        if local_key is not None:
            scale_key = local_key
        elif scale_key is None:
            for fallback in _CONTEXT_FALLBACK_KEYS:
                value = node.get(fallback)
                if value:
                    scale_key = f"{fallback}:{value}"
                    break

        result = {}
        for key, value in node.items():
            if key in _REDACT_KEYS:
                result[key] = None if value is not None else value
            elif key in _FAKE_PREVIEW_KEYS:
                result[key] = _FAKE_PDF_PREVIEW_BASE64 if value else value
            elif key == KNOWN_NAMES_KEY:
                result[key] = _fake_known_names(value)
            elif key == PARTICIPANTS_KEY:
                result[key] = _fake_participants(value)
            elif key == BANK_ACCOUNTS_KEY:
                result[key] = _fake_bank_accounts(value)
            elif key in PERSON_NAME_KEYS:
                result[key] = fake_person_name(value) if isinstance(value, str) else value
            elif key in NAME_KEYS:
                result[key] = fake_name(value) if isinstance(value, str) else value
            elif key in IDENTIFIER_KEYS:
                result[key] = fake_identifier(value, key) if isinstance(value, str) else value
            elif key in _LIST_IDENTIFIER_KEYS:
                kind = _LIST_IDENTIFIER_KEYS[key]
                if isinstance(value, list):
                    result[key] = [
                        fake_identifier(v, kind) if isinstance(v, str) else v for v in value
                    ]
                else:
                    result[key] = value
            elif key in _UNCONDITIONAL_TEXT_KEYS or (
                key in _TRANSACTION_TEXT_KEYS and _looks_like_transaction_row(node)
            ):
                result[key] = fake_transaction_text(value, key) if isinstance(value, str) else value
            elif key == "description" and _looks_like_timesheet_row(node):
                result[key] = (
                    fake_transaction_text(value, "work_description")
                    if isinstance(value, str)
                    else value
                )
            elif key == "note" and _looks_like_vacation_row(node):
                result[key] = (
                    fake_transaction_text(value, "vacation_note")
                    if isinstance(value, str)
                    else value
                )
            elif key == "note" and (
                _looks_like_transaction_row(node) or _looks_like_invoice_row(node)
            ):
                result[key] = (
                    fake_transaction_text(value, "note") if isinstance(value, str) else value
                )
            elif key in AMOUNT_KEYS:
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    result[key] = fake_amount(float(value), scale_key or _UNSCOPED_KEY)
                else:
                    result[key] = _anonymize_node(value, scale_key)
            elif key in AMOUNT_DICT_KEYS and isinstance(value, dict):
                result[key] = {
                    label: (
                        fake_amount(float(v), scale_key or _UNSCOPED_KEY)
                        if isinstance(v, (int, float)) and not isinstance(v, bool)
                        else v
                    )
                    for label, v in value.items()
                }
            else:
                result[key] = _anonymize_node(value, scale_key)
        return result
    if isinstance(node, list):
        return [_anonymize_node(item, scale_key) for item in node]
    return node


def anonymize(payload, scale_key: str | None = None):
    """Recursive dict/list walker that masks names/amounts/identifiers.

    Any other key (numeric/db ids, dates, `payment_status`, `direction`,
    `currency`, sync/audit metadata, ...) is passed through unchanged.
    """
    return _anonymize_node(payload, scale_key)
