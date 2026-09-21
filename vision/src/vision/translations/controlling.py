"""English translations for the controlling UI area."""

from __future__ import annotations

TRANSLATIONS: dict[str, str] = {
    # controlling_projects.html
    "Ötlet": "Idea",
    "Számlázható": "Billable",
    "Új": "New",
    "Projektek listája és kezelése — csak Open státuszú projektre rögzíthető új idő.": (
        "List and manage projects — new time can only be logged against a project with "
        "Open status."
    ),
    "Azonosító / rövid név": "ID / short name",
    "Ügyfél": "Client",
    "Project gazda": "Project owner",
    "Típus": "Type",
    "Kezdés dátuma": "Start date",
    "Tervezett végdátum": "Planned end date",
    "Státusz": "Status",
    "Terv. napszám": "Planned days",
    "Óra": "Hours",
    "Nincs tervezett végdátum: T&M, nem fix scope-ú projekt": (
        "No planned end date: T&M, not a fixed-scope project"
    ),
    "Ledolgozott nap (8 órás nap):": "Days worked (8-hour day):",
    "Módosít": "Edit",
    "Megtekintés": "View",
    "Nem törölhető: a projekthez már vannak rögzített timesheet bejegyzések": (
        "Cannot be deleted: the project already has recorded timesheet entries"
    ),
    "Töröl": "Delete",
    "Biztosan törli?": "Are you sure you want to delete?",
    "Új projekt": "New project",
    "Kezdjen gépelni…": "Start typing…",
    "Ügyfelenként külön sorszámozás (Ügyfelek törzsadat)": (
        "Separate numbering per client (Clients master data)"
    ),
    "pl. FVM": "e.g. FVM",
    "pl. 20": "e.g. 20",
    "Válasszon…": "Select…",
    "A jövőben a költséghely-felelős — read only jogosultsággal nem lehet": (
        "In the future, the cost-center owner — cannot be a read-only user"
    ),
    "Csak Open státuszú projektre rögzíthető új idő": (
        "New time can only be logged against a project with Open status"
    ),
    "Ha üresen marad: T&M, nem fix scope-ú projekt": (
        "If left blank: T&M, not a fixed-scope project"
    ),
    "Tervezett napszám": "Planned days",
    "Hány napra szerződtünk — a ledolgozott nappal (Óra/8) összevetve": (
        "How many days were contracted — compared against days worked (Hours/8)"
    ),
    "Sorszám": "Sequence number",
    "Automatikusan javasolt, ügyfelenként növekvő": "Automatically suggested, incrementing per client",
    "Project kód": "Project code",
    "Automatikusan összeállítva: azonosító-sorszám": "Automatically composed: id-sequence number",
    "Projekt célja": "Project goal",
    "Rövid leírás a projekt céljáról…": "Short description of the project's goal…",
    "Projekt leszállítandó(k)": "Project deliverable(s)",
    "Mikor tekinthető sikeresnek a projekt, milyen eredményterméket kell átadni…": (
        "When is the project considered successful, what deliverable needs to be handed over…"
    ),
    "Rögzítésre jogosultak (permitted_users)": "Authorized to log time (permitted_users)",
    "A project gazda mindig jogosult (ezért nincs a listában). Csak a kijelölt felhasználók "
    "adhatnak timesheet rekordot a projekthez": (
        "The project owner is always authorized (which is why they're not in the list). "
        "Only the selected users can log timesheet records against the project"
    ),
    "Mégse": "Cancel",
    "Mentés": "Save",
    "Projekt módosítása": "Edit project",
    "Projekt megtekintése": "View project",
    "Read only jogosultságú felhasználó nem választható project gazdának": (
        "A read-only user cannot be selected as project owner"
    ),
    "Ügyfélváltáskor újra kiosztásra kerül": "Reassigned when the client changes",
    "Csak a kijelölt felhasználók adhatnak timesheet rekordot a projekthez": (
        "Only the selected users can log timesheet records against the project"
    ),
    "Bezár": "Close",
    # controlling_reports.html
    "Nyomtatás": "Print",
    "Lekérdezések és exportok — az eredmény kereshető táblázatként jelenik meg.": (
        "Queries and exports — the result appears as a searchable table."
    ),
    "Riportválasztó és szűrők": "Report selector and filters",
    "Riport típus": "Report type",
    "Dátumtartomány": "Date range",
    "Egyéni dátumtól": "Custom date from",
    "Egyéni dátumig": "Custom date to",
    "mind": "all",
    "Projekt": "Project",
    "Személy": "Person",
    "Tevékenység típus": "Activity type",
    "Riport futtatása": "Run report",
    "Heti alakulás": "Weekly trend",
    "Napi": "Daily",
    "Heti": "Weekly",
    "Havi": "Monthly",
    "Összes": "All",
    "Összesen": "Total",
    "óra": "hours",
    "Napok száma": "Number of days",
    "Átlag / aktív hét": "Average / active week",
    "Átlag / Nap": "Average / Day",
    "Egyéb": "Other",
    "jan": "Jan",
    "feb": "Feb",
    "márc": "Mar",
    "ápr": "Apr",
    "máj": "May",
    "jún": "Jun",
    "júl": "Jul",
    "aug": "Aug",
    "szept": "Sep",
    "okt": "Oct",
    "nov": "Nov",
    "dec": "Dec",
    "Eredmény": "Result",
    "Időszak": "Period",
    "Projekt hét": "Project week",
    "Heti (óra)": "Weekly (hours)",
    "Heti (nap)": "Weekly (days)",
    "Kumulált (óra)": "Cumulative (hours)",
    "Kumulált (nap)": "Cumulative (days)",
    "Dátum": "Date",
    "Nap": "Day",
    "Hét": "Week",
    "Résztvevők": "Participants",
    "Leírás": "Description",
    "Órák a szűrt sorokban:": "Hours in the filtered rows:",
    "Heti sor → Timesheet az adott projektre szűrve": "Weekly row -> Timesheet filtered to that project",
    "Bejegyzések": "Entries",
    "napi részletek": "daily details",
    "Összesítés": "Summary",
    "Összesen (óra)": "Total (hours)",
    "Bejegyzések száma": "Number of entries",
    "Mindösszesen": "Grand total",
    "Tiro — Controlling riport": "Tiro — Controlling report",
    # controlling_timesheet.html
    "Munkaidő rögzítés": "Time logging",
    "Projekt szűrő": "Project filter",
    # controlling_vacation.html / partials/vacation_content.html
    "Szabadság bejegyzés módosítása": "Edit vacation entry",
    "Csapat szabadság / elérhetőség bejegyzései.": "Team vacation / availability entries.",
    "Kezdete": "Start",
    "Vége": "End",
    "Megjegyzés": "Note",
    "Felhasználó": "User",
    "Biztosan törli ezt a bejegyzést?": "Are you sure you want to delete this entry?",
    "Új szabadság bejegyzés": "New vacation entry",
    "Opcionális megjegyzés…": "Optional note…",
    # partials/timesheet_content.html
    "timesheet rekordjai.": "timesheet records.",
    "Tevékenység": "Activity",
    "Biztosan törli ezt a rekordot?": "Are you sure you want to delete this record?",
    "Összesítő (szűrt):": "Summary (filtered):",
    "Új timesheet rekord": "New timesheet record",
    "Csak az Ön számára engedélyezett projektek választhatók": (
        "Only projects you are authorized for can be selected"
    ),
    "Időráfordítás (óra)": "Time spent (hours)",
    "0,5 órás lépésekben": "In 0.5-hour steps",
    "pl. Kozma Zoltán, Erős Péter": "e.g. Kozma Zoltán, Erős Péter",
    "Tevékenység (szabad szöveges leírás)": "Activity (free-text description)",
    "A konkrét rekord leírása…": "The specific record's description…",
    "A projektből automatikusan adódik": "Derived automatically from the project",
    "Automatikusan számolt (W1-től)": "Automatically calculated (from W1)",
    "Timesheet rekord módosítása": "Edit timesheet record",
    "(nem elérhető)": "(not available)",
}
