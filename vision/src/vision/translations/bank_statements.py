"""English translations for the bank statements UI area."""

from __future__ import annotations

TRANSLATIONS: dict[str, str] = {
    # bank_statements.html
    # "Bankkivonatok" itself is translated in translations/common.py (used
    # identically in the sidebar nav) — not re-declared here to avoid drift.
    "Feltöltött PDF kivonatok és a feldolgozott CSV kivonatok — mindkettő letölthető.": (
        "Uploaded PDF statements and processed CSV statements — both downloadable."
    ),
    "PDF bankkivonat feltöltése — húzd ide, vagy": "Upload a PDF bank statement — drag it here, or",
    "tallózás": "browse",
    "Bank kézi megadása (opcionális)": "Manually specify bank (optional)",
    "Automatikus detektálás": "Automatic detection",
    "Felülírás": "Overwrite",
    "Feltöltés": "Upload",

    # transactions.html
    "Bank Tranzakciók": "Bank Transactions",
    "Bank tranzakció részletei": "Bank transaction details",
    "Válasszon ki egy tranzakciót a listából.": "Select a transaction from the list.",

    # partials/bank_statement_table.html
    "Típus": "Type",
    "Fájlnév": "Filename",
    "Időszak": "Period",
    "Méret": "Size",
    "Módosítva": "Modified",
    "Művelet": "Action",
    "Letöltés": "Download",
    "Biztosan törli?": "Are you sure you want to delete?",
    "Nincs feltöltött bankkivonat": "No bank statements uploaded",

    # partials/transaction_table.html
    "Nettó": "Net",
    "Bank egyenleg": "Bank balance",
    "Tranzakció ID": "Transaction ID",
    "Dátum": "Date",
    "Összeg": "Amount",
    "Kapcsolt számla": "Linked invoice",
    "Referencia": "Reference",
    "Leírás": "Description",
    "Manuálisan zárolva": "Manually locked",
    "Nincs partner hozzárendelve": "No partner assigned",
    "nincs partner": "no partner",

    # partials/transaction_detail.html
    "Irány": "Direction",
    "Egyenleg": "Balance",
    "Kategória": "Category",
    "Partner neve": "Partner name",
    "Bankkód": "Bank code",
    "Partner címe": "Partner address",
    "Küldő címe": "Sender address",
    "Díjak összesen": "Total fees",
    "Deviza / kártya": "Currency / card",
    "Árfolyam": "Exchange rate",
    "Kártya": "Card",
    "Megjegyzés": "Note",
    "Kapcsolatok": "Links",
    "Számla": "Invoice",
    "Kapcsolat törlése": "Remove link",
    "Számla kapcsolása": "Link invoice",
    "PDF fájl": "PDF file",
    "Manuálisan kapcsolva": "Manually linked",
    "PDF kapcsolat törlése": "Remove PDF link",
    "PDF kapcsolása": "Link PDF",
    "Szállító": "Supplier",
    "Szállító leválasztása": "Unlink supplier",
    "Szállító kapcsolása": "Link supplier",
    "Vevő": "Customer",
    "Vevő leválasztása": "Unlink customer",
    "Vevő kapcsolása": "Link customer",
    "Létrehozva": "Created",

    # partials/picker_transactions.html
    "Bruttó": "Gross",
    "Státusz": "Status",
    "Kiválaszt": "Select",

    # partials/transaction_detail.html — disambiguated from the invoice-number
    # sense of "Számlaszám" (owned by translations/invoices.py), since "számla"
    # means both "invoice" and bank "account" in Hungarian. Same translation
    # as translations/invoices.py's own "Bankszámlaszám" entry (supplier/
    # customer bank account number) — kept in sync intentionally.
    "Bankszámlaszám": "Bank account number",
}
