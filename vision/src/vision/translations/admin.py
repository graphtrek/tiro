"""English translations for the admin UI area."""

from __future__ import annotations

TRANSLATIONS: dict[str, str] = {
    # admin_activity_types.html
    # "Tevékenység típusok" itself is translated in translations/common.py
    # (used identically in the sidebar nav) — not re-declared here.
    "Új": "New",
    "A timesheet rögzítésnél választható típusok karbantartása — törlés helyett inaktiválás.": (
        "Maintain the types selectable when recording timesheets — deactivate instead of delete."
    ),
    # "Elnevezés" (not "Megnevezés") — deliberately a different Hungarian
    # source word from translations/invoices.py's "Megnevezés": "Description",
    # since here it means the activity type's own name, not a line-item
    # description; sharing "Megnevezés" would have collided in the merged
    # TRANSLATIONS dict.
    "Elnevezés": "Name",
    "Státusz": "Status",
    "Használat (rekordok száma)": "Usage (number of records)",
    "aktív": "active",
    "inaktív": "inactive",
    "Módosít": "Edit",
    "Töröl": "Delete",
    "Biztosan törli?": "Are you sure you want to delete?",
    "Inaktiválás — a típust rekordok használják": "Deactivate — the type is used by records",
    "Új tevékenység típus": "New activity type",
    "Bezárás": "Close",
    "pl. Oktatás": "e.g. Training",
    "Egyedinek kell lennie": "Must be unique",
    "Mégse": "Cancel",
    "Mentés": "Save",
    "Tevékenység típus módosítása": "Edit activity type",
    "Inaktív típus új rekordhoz nem választható; a meglévő rekordok érintetlenek": (
        "An inactive type cannot be selected for new records; existing records are unaffected"
    ),
    # admin_audit.html
    "Felhasználói módosítások naplója — melyik oldalon, melyik rekordot, mit és mikor.": (
        "Log of user changes — which page, which record, what and when."
    ),
    "Időpont": "Time",
    "Felhasználó": "User",
    "Menü": "Menu",
    "Rekord": "Record",
    "Gomb": "Button",
    "Részletek": "Details",
    "Megszemélyesítve": "Impersonated",
    "létrehozás": "create",
    "törlés": "delete",
    "módosítás": "update",
    # admin_users.html
    "Felhasználók": "Users",
    "Név": "Name",
    "Utolsó belépés": "Last login",
    "Regisztrálva": "Registered",
    "Belépés e felhasználóként": "Log in as this user",
    # sync.html
    # "Szinkronizálás" itself is translated in translations/dashboard.py (also
    # used in pitch.html) as "Sync", matching the sidebar nav's existing
    # bare "Sync" label — not re-declared here to avoid drift.
    "Sync indítása": "Start sync",
    "Dátumtól": "Date from",
    "Dátumig": "Date to",
    "Sync mód": "Sync mode",
    "Teljes (NAV + PDF + Bank + összekapcsolás)": "Full (NAV + PDF + Bank + matching)",
    "Csak NAV számlák": "NAV invoices only",
    "Csak PDF fájlok": "PDF files only",
    "Csak bank tranzakciók (Erste + Wise CSV)": "Bank transactions only (Erste + Wise CSV)",
    "Csak összekapcsolás": "Matching only",
    "Szinkronizálás folyamatban...": "Synchronization in progress...",
    "Sync napló": "Sync log",
    "utolsó": "last",
    "futás": "runs",
    "hiba": "error",
    "figyelmeztetés": "warning",
    "NAV számla": "NAV invoice",
    "Időtartam": "Duration",
    "Befejezve": "Finished",
    # partials/pending_sync_card.html
    "számla": "invoice",
    "és": "and",
    "tranzakció": "transaction",
    "vár partner hozzárendelésre — hozza létre a hiányzó szállítót/vevőt a Szállítók/Vevők oldalon.": (
        "is waiting for a partner assignment — create the missing supplier/customer on the "
        "Suppliers/Customers page."
    ),
    # partials/sync_result.html
    "Sync befejezve": "Sync finished",
    "Sync sikeres": "Sync successful",
    "PDF fájl": "PDF file",
    "Bank tranzakció": "Bank transaction",
    "PDF összekapcsolva": "PDF matched",
}
