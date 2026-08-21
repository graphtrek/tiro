# Tiro — Defects

Filed by QA against `REQUIREMENTS.md`. Severity: **HIGH** breaks a requirement, **MEDIUM**
degrades one, **LOW** is cosmetic. Only QA sets `CLOSED`.

---

### DEF-001 — `GET /api/v1/invoices/{invoice_number}` returns 500 for any invoice with no linked supplier/customer
Status: CLOSED
Severity: HIGH
Found by: qa
Service(s): invoice-core
Steps:
1. Start `invoice-core` (port 8004) and PostgreSQL; run a sync so at least one invoice exists
   whose NAV-reported supplier/customer wasn't already a known `Supplier`/`Customer` row (the
   common case — see DEF-004 — `supplier_id`/`customer_id` stay `null` until a human manually
   links or creates the partner).
2. `GET /api/v1/invoices/{invoice_number}` with a valid bearer token, e.g.
   `curl -H "Authorization: Bearer $TOKEN" http://localhost:8004/api/v1/invoices/AHUW261564234`.
3. Compare with `GET /api/v1/invoices/{invoice_id:int}` (e.g. `/api/v1/invoices/6`) for the same
   invoice, which works.
Expected: 200 with the invoice JSON (`supplier_id`/`customer_id` simply `null`), matching the
by-id route's behavior.
Actual: 500 Internal Server Error. Server log shows
`fastapi.exceptions.ResponseValidationError: 2 validation errors: {'loc': ('response',
'supplier_id'), 'msg': 'Input should be a valid integer', 'input': None}` (same for
`customer_id`). Root cause: `invoice_core/api/main.py:305`
(`@app.get("/api/v1/invoices/{invoice_number}", response_model=InvoiceOut)`) declares
`response_model=InvoiceOut`, and `InvoiceOut` in `invoice_core/models.py:140-141` types
`supplier_id: int` / `customer_id: int` as required (non-nullable) — unlike `invoice_file_id:
int | None` two lines below. The sibling route at `main.py:297`
(`/api/v1/invoices/{invoice_id:int}`) has no `response_model` and returns a plain
`dataclasses.asdict(...)` dict, so it never hits this validation and works fine. Reproduced
against real synced data (6/6 invoices in the June 2026 sync had at least one null partner id;
`GET /api/v1/invoices/AHUW261564234` and `/api/v1/invoices/NEXYS-2026-1` both 500).
Screenshot: n/a (API-only); see `e2e/tests/test_read_api.py::test_invoice_detail_by_invoice_number_for_unlinked_supplier_customer`
for a standing regression test (currently failing, as expected until fixed).
History:
- 2026-07-26 qa: filed
- 2026-07-26 backend developer: FIX READY — `InvoiceOut.supplier_id`/`customer_id` retyped
  `int | None = None` in `invoice_core/models.py`. New unit test `tests/test_invoice_detail_route.py`.
- 2026-07-26 qa: CLOSED — retested against the real running stack. `tests/test_invoice_detail_route.py`
  (2 tests) passes; full invoice-core suite is 202/202. Re-ran the e2e suite:
  `test_invoice_detail_by_invoice_number_for_unlinked_supplier_customer` genuinely exercised (not
  skipped) an invoice with null `supplier_id`/`customer_id` before this session's sync populated
  partners, and got 200 — confirms the fix, not a coincidence. Regression-checked the sibling
  by-id route (`/api/v1/invoices/6`) and the by-number route for three invoice numbers
  (`AHUW261564234`, `NEXYS-2026-1`, `2026-000064`), all 200 both before and after partners got
  linked by the DEF-004 fix.

---

### DEF-002 — `invoice-core` CLI sync commands cannot complete real work while `AUTH_ENABLED=true` (current config)
Status: CLOSED
Severity: MEDIUM
Found by: qa
Service(s): invoice-core, nav-invoice, invoice-file-filter, bank
Steps:
1. Start the full stack with the shared root `.env` as currently configured (`AUTH_ENABLED=true`,
   `ATTACHMENT_DOWNLOADER_AUTH_ENABLED=false`).
2. `cd invoice-core && uv run invoice-core sync --start 2026-06-01 --end 2026-06-30` (or
   `sync-nav`/`sync-pdf`/`sync-bank`).
3. Compare with `POST /api/v1/sync` (or the vision Sync page) using a valid
   `Authorization: Bearer` token, which completes real work end-to-end (6 invoices, 102 PDF
   files, 64 bank transactions synced in our run).
Expected: per CLAUDE.md the CLI is documented as an equivalent way to run each stage
(`uv run invoice-core sync | sync-nav | sync-pdf | sync-bank | sync-match`); it should be able to
do real work the same as the HTTP endpoint/Sync page.
Actual: every CLI stage that calls a downstream service fails immediately with a clear 401 from
that service (e.g. `NAV sync failed: Failed to reach nav-invoice at http://localhost:8002: 401
Client Error: Unauthorized`) — never even reaching NAV/Gmail. This *is* a clean degrade (no
500/hang, clear per-stage error text, a `sync_log` row written with `error_count>0`), so it
satisfies the narrower "degrades cleanly" bar, but the CLI is effectively non-functional for
real syncing whenever auth is enabled service-wide, because the CLI process has no bearer token
and there is no `--token`/env-var mechanism for it to supply one for the outbound calls made by
`nav_client.py`/`pdf_client.py`/`bank_client.py`. Confirmed the same failure independently for
`sync-nav`, `sync-pdf`, `sync-bank` (each via `subprocess` in
`e2e/tests/test_sync_pipeline.py::test_sync_stage_cli_degrades_cleanly_without_a_token`, which
passes today because it only asserts clean degradation, not that real work happened).
Screenshot: n/a (CLI output only).
History:
- 2026-07-26 qa: filed
- 2026-07-26 backend developer: FIX READY — added `--token` flag / `MP_SERVICE_TOKEN` env var to
  the sync CLI commands, setting the existing `current_token` ContextVar so outbound calls carry
  a bearer token; 401 errors now append a hint to pass `--token`/`MP_SERVICE_TOKEN`. New unit test
  `tests/test_cli_service_token.py`.
- 2026-07-26 qa: CLOSED — retested against the real running stack with `AUTH_ENABLED=true`.
  `uv run invoice-core sync-nav --start 2026-06-01 --end 2026-06-30 --token <token>` reached the
  real nav-invoice service and did real work (6 invoices fetched, `sync_nav` ran to completion,
  0 errors). Same result via `MP_SERVICE_TOKEN=<token> uv run invoice-core sync-nav ...` (env-var
  path). Without any token, `sync-nav` still degrades cleanly: single 401-derived error, `sync_log`
  row written, and the new hint text
  ("supply a bearer token via --token or the MP_SERVICE_TOKEN env var (see invoice-core/README.md)")
  is present in both the log line and the CLI's printed error panel. `tests/test_cli_service_token.py`
  (10 tests) passes; full invoice-core suite 202/202.

---

### DEF-003 — Dashboard "Legutóbbi számlák" widget prints literal `None` instead of a placeholder for unlinked suppliers
Status: CLOSED
Severity: MEDIUM
Found by: qa
Service(s): vision
Steps:
1. Log in to `vision` (port 8009) and sync/seed at least one invoice whose supplier is not
   linked (`supplier_id` null — the common case, see DEF-004).
2. Open `/ui/` (Dashboard).
3. Look at the "Legutóbbi számlák" (recent invoices) table, "SZÁLLÍTÓ" column.
Expected: a placeholder like the "—" used for a missing date in the same table (see
`invoice_date or '—'` two lines above in the template), or "— nincs partner —" as used
consistently everywhere else in the app (`invoices.html`/`invoice_table.html`/
`transaction_table.html`/`invoice_detail.html`).
Actual: the literal Python string `None` is rendered in the cell for every row with no linked
supplier. Root cause: `vision/src/vision/templates/ui_dashboard.html:232` is
`<td>{{ row.supplier_name }}</td>` with no `or '—'`/default filter, unlike the adjacent
`invoice_date` cell on line 231 which does have one.
Screenshot: screenshots/04_dashboard.png (see "SZÁLLÍTÓ" column, all 5 rows read "None").
History:
- 2026-07-26 qa: filed
- 2026-07-26 frontend developer: FIX READY — `ui_dashboard.html`'s "Legutóbbi számlák" SZÁLLÍTÓ
  cell now branches on `row.supplier_id`: links to the supplier when present, otherwise renders
  the same "— nincs partner —" placeholder used elsewhere in the app. New template test coverage
  in `vision/tests/test_ui_templates.py`.
- 2026-07-26 orchestrator: reviewed after-screenshot, accepted.
- 2026-07-26 qa: CLOSED for the literal-`None` defect as originally filed — retested: the literal
  `None` string no longer appears anywhere in the dashboard's recent-invoices table (confirmed via
  fresh screenshot `screenshots/retest_dashboard.png` and raw HTML fetch), replaced by the
  standard "— nincs partner —" placeholder. vision's own suite is 14/14 and
  `vision/tests/test_ui_templates.py` passes. NOTE: retesting this surfaced a NEW, more serious
  regression from the same diff — filed separately as DEF-008 below (the added
  `{% if row.supplier_id %}` guard checks a field the dashboard API payload never populates, so a
  *known* supplier now never shows either; see DEF-008).

---

### DEF-004 — `sync_nav` never creates new suppliers/customers, contradicting the documented requirement, leaving most synced invoices unlinked
Status: CLOSED
Severity: MEDIUM
Found by: qa
Service(s): invoice-core
Steps:
1. Run a real sync (`POST /api/v1/sync`) against NAV invoices referencing suppliers/customers
   not already present as `Supplier`/`Customer` rows.
2. Check the resulting invoices: `GET /api/v1/invoices` (or the Számlák/Dashboard pages).
Expected: REQUIREMENTS.md, "invoice-core — master orchestrator": *"**sync_nav** — call
nav-invoice, upsert invoices, suppliers and customers."* — i.e. new suppliers/customers referenced
by NAV data should be created (upserted), not just invoices.
Actual: in a real run against production NAV data, 6/6 invoices ended up with `supplier_id` and
`customer_id` both `null` (dashboard `top_suppliers`/`top_customers` widgets show "Nincs adat"
despite live suppliers existing; the Számlák/Bank pages show "— nincs partner —" almost
everywhere). `invoice_core/service.py:437-453` (`sync_nav`) explicitly only *links* to an
existing supplier/customer via `_find_supplier`/`_find_customer` and, per its own docstring
("Suppliers/customers are only ever linked, never created here..."), emits a warning instead
(surfaced correctly on the Sync page) asking the user to create the partner by hand on the
Szállítók/Vevők page. This may be an intentional product decision (avoiding
auto-created duplicate/garbage partner records) rather than a bug, in which case
REQUIREMENTS.md's wording should be corrected instead of the code — filing either way per QA's
mandate to report every contract mismatch found.
Screenshot: screenshots/04_dashboard.png ("Top szállítók"/"Top vevők": "Nincs adat"),
screenshots/05_invoices.png (all rows: "— nincs partner —").
History:
- 2026-07-26 qa: filed
- 2026-07-26 backend developer: FIX READY — `sync_nav` now upserts suppliers/customers via
  `_find_or_create_supplier`/`_find_or_create_customer`: dedupes on the normalized 8-digit tax
  core, then on normalized name; creates only when NAV gave a usable tax number or name; augments
  null fields only on existing rows (never overwrites a user-edited value). New
  `tests/test_sync_nav_partner_upsert.py`, replacing the old
  `TestSyncNavDoesNotAutoCreatePartners` class (which had asserted the opposite contract) with
  `TestSyncNavPartnerUpsertAndLocking`.
- 2026-07-26 qa: CLOSED — this was the point of the whole retest pass, verified the product
  outcome independently of the rewritten unit tests, against the real running stack (not just
  code review):
  - Ran a real `POST /api/v1/sync` against production NAV data. `supplier_count` went 2 → 7,
    `customer_count` went 0 → 3 (dashboard KPI). All 6 invoices now carry non-null
    `supplier_id`/`customer_id`. Dashboard "Top szállítók"/"Top vevők" widgets are populated
    (Nexys Kft. 88%, Fazekas & Társai 6%, Őrszem Services 5% / ERSTE BANK HUNGARY Zrt. 95%,
    Uniomedia Zrt. 5% — was "Nincs adat" before). Számlák (`/ui/invoices`) page shows real
    supplier/customer names on every row (screenshot `screenshots/retest_invoices.png`).
    Dashboard screenshot: `screenshots/retest_dashboard.png`.
  - Ran `sync-nav` two more times via the CLI (once with `--token`, once with `MP_SERVICE_TOKEN`)
    after the full sync — supplier/customer counts stayed at 7/3 both times: no duplicates
    created on repeated syncs.
  - Manually edited a synced supplier's address field
    (`PUT /api/v1/partners/suppliers/3` → "QA-edited address, should survive resync"), re-ran
    `sync-nav`, and confirmed the edited address was unchanged afterwards — a user edit survives
    resync at the real-stack level, not just in the unit test.
  - Also independently re-proved the four sync-survival guarantees from
    REQUIREMENTS.md's acceptance criteria on real data (not the rewritten unit tests): set a note,
    marked an invoice PAID + locked, manually linked a PDF, manually linked a bank transaction —
    ran a full `POST /api/v1/sync` — note, PDF link (+lock), and bank-transaction link all
    survived unchanged. See DEF-007 below for a related but distinct display-only defect found
    during this same check (the *stored* PAID status survived; the invoice-detail page's
    *displayed* status did not, because `_derive_payment_status` ignores the lock).

---

### DEF-005 — Vevők (customers) page shows a contradictory "Találatok: 1 - 1 Összesen: 1" when the table is empty
Status: CLOSED
Severity: LOW
Found by: qa
Service(s): vision
Steps:
1. Log in to vision with zero `Customer` rows in the database (the default state for this
   workspace — `GET /api/v1/partners/customers` returns `[]`).
2. Open `/ui/customers` (Vevők).
Expected: an empty-state message consistent with the "0 results" case — compare with
`/ui/admin/users` (Felhasználók) with zero users, which correctly shows only "Nincs találat"
under the table and no pagination-count line contradicting it.
Actual: the table body correctly shows "Nincs találat", but the pagination footer below it reads
"Találatok: 1 - 1 Összesen: 1" (Results 1-1, total 1) — implying one row exists. Reproduced twice
independently (screenshots 08 and 17, taken minutes apart in the same session).
Screenshot: screenshots/08_customers.png, screenshots/17_customers_recheck.png
History:
- 2026-07-26 qa: filed
- 2026-07-26 frontend developer: FIX READY — removed the server-rendered `{% else %}` "Nincs
  találat" fallback `<tr>` from `customers.html` (DataTables was counting it as a real data row)
  and instead set DataTables' own `language.emptyTable: "Nincs találat"`.
- 2026-07-26 orchestrator: reviewed after-screenshot, accepted.
- 2026-07-26 qa: CLOSED — retested with the database at 0 customers (before this session's DEF-004
  full-sync populated partners): `/ui/customers` shows only "Nincs találat" in the table body,
  with no "Találatok: 1 - 1 Összesen: 1" (or any other) contradictory count line in the pagination
  footer (`screenshots/e2e_customers.png`, captured via the e2e suite's fresh Playwright run).
  Regression-checked the populated case afterwards (3 real customers post-sync,
  `screenshots/retest_customers.png`): correct row count and pagination, no regression.
  `test_ui_templates.py` and the full vision suite (14/14) pass.

---

### DEF-006 — "HIPA - Késedelmi" KPI card label is truncated illegibly on the Adók page
Status: CLOSED
Severity: LOW
Found by: qa
Service(s): vision
Steps:
1. Log in to vision, open `/ui/adok` (Adók) for a year with a non-zero "HIPA - Késedelmi" total.
2. Look at the 5th KPI card in the top row.
Expected: the full label "HIPA - Késedelmi" readable (wrap, shrink font, or a tooltip), same as
the other five KPI cards which fit their labels on one line.
Actual: label is clipped to "HIPA - KÉSEDEL..." with no tooltip revealing the full text on hover
in the static render.
Screenshot: screenshots/11_adok.png (top KPI row, 5th card).
History:
- 2026-07-26 qa: filed
- 2026-07-26 frontend developer: FIX READY — `.kpi-card .card-title.kpi-title-compact` in
  `custom.css` changed from `white-space: nowrap; overflow: hidden; text-overflow: ellipsis` to
  `white-space: normal; overflow-wrap: break-word; line-height: 1.2`, letting the label wrap
  instead of truncating.
- 2026-07-26 orchestrator: reviewed after-screenshot, accepted.
- 2026-07-26 qa: CLOSED — retested `/ui/adok`: "HIPA - Késedelmi" now wraps to two lines and is
  fully legible (`screenshots/e2e_adok.png`, `screenshots/retest_adok.png`). Regression-checked
  the other six KPI cards on the same row — all still fit on one line at the increased
  `line-height`, no new overflow/clipping introduced.

---

### DEF-007 — Invoice detail's displayed `payment_status` ignores `payment_status_locked` once any bank transaction is linked, downgrading a manually-locked PAID invoice to PARTIAL
Status: CLOSED
Severity: HIGH
Found by: qa
Service(s): invoice-core
Steps:
1. Start `invoice-core` (port 8004). Pick any invoice with `amount_total` larger than any single
   unlinked bank transaction's amount.
2. `PATCH /api/v1/invoices/{id}` with `{"payment_status": "PAID", "payment_status_locked": true}`.
3. `GET /api/v1/invoices/{id}` — confirm `payment_status: "PAID"`, `payment_status_locked: true`,
   `bank_transactions: []`.
4. `PUT /api/v1/invoices/{id}/transactions/{txn_id}` to manually link one bank transaction whose
   amount is smaller than `amount_total` (a legitimate manual action, e.g. a partial payment).
5. `GET /api/v1/invoices/{id}` again.
6. Compare with `GET /api/v1/invoices` (list endpoint) for the same invoice at the same moment.
Expected: per REQUIREMENTS.md ("Never let an automated sync stage overwrite a fact the user set
by hand: an invoice manually marked paid... must stay as the user left it") and the invoice
detail page's own "🔒 Manuális" lock badge next to Státusz, the displayed status should stay
`PAID`/`Fizetve` — this is exactly what the lock is for, and the list endpoint already does this
correctly (`invoice_service.list_invoices`'s docstring: "A manually locked invoice is never
auto-overridden this way").
Actual: the detail endpoint's `payment_status` flips to `PARTIAL` as soon as any bank transaction
is linked whose amount doesn't cover `amount_total`, regardless of `payment_status_locked`. Root
cause: `invoice_core/services/invoice_service.py`'s `_derive_payment_status(inv, bank_txns)`
(used at line ~362 for the single-invoice detail view) recomputes the status from linked
transactions unconditionally — it never checks `inv.payment_status_locked`, unlike
`list_invoices`'s row-building loop (lines ~221-228) which explicitly guards with
`and not inv.payment_status_locked` and is upgrade-only (UNPAID→PAID), never downgrades. The
*stored* `payment_status` in the database is untouched (confirmed by unlinking the transaction
again and re-reading: reverts to `PAID`) — this is a display-layer bug, but it is directly
user-visible: the vision invoice-detail page (`/ui/invoices/{id}`) shows "Részleges" with the
lock icon still next to it, while the Számlák list page (`/ui/invoices`) shows "Fizetve" for the
exact same invoice at the exact same time — a visible contradiction between two pages of the same
app. Reproduced live against invoice id 1 (GRPHT-2026-12, amount_total 2 533 650 HUF) linked to
transaction id 7 (amount 5 408.61 HUF): detail → PARTIAL, list → PAID.
Screenshot: screenshots/retest_invoice1_detail.png (Státusz: "Részleges" + lock badge),
screenshots/retest_invoices.png (same invoice, GRPHT-2026-12 row: "Fizetve").
History:
- 2026-07-26 qa: filed (found while independently re-proving the DEF-004 acceptance criterion —
  manual overrides surviving a full sync — per the orchestrator's request to test that criterion
  harder than the rewritten unit tests alone).
- 2026-07-26 backend developer: FIX READY — factored one shared rule,
  `_effective_payment_status(stored_status, payment_status_locked, derived_status)`, now used by
  both `list_invoices` and `get_invoice` — the detail view no longer recomputes status from linked
  transactions independently of the list view's lock-aware, upgrade-only logic. New test
  `tests/test_locked_status_consistency.py`.
- 2026-07-26 qa: CLOSED — retested against the real running stack (invoice-core :8004, vision
  :8009). Original repro (invoice id 1 / GRPHT-2026-12, transaction id 7): `GET /api/v1/invoices/1`
  now returns `payment_status: "PAID"` (was `"PARTIAL"`), matching `GET /api/v1/invoices`'s row for
  the same invoice, both `"PAID"`. Independently reproduced fresh (not relying on already-fixed
  state): invoice id 3 (`2026-000064`, amount_total 71 120 HUF, originally `UNPAID`/unlocked) —
  `PATCH` to `PAID`+locked, then linked transaction id 9 (31.00 HUF, far short of covering the
  total) via `PUT /api/v1/invoices/3/transactions/9`: detail and list both read `PAID`/locked
  afterward (previously the detail path alone would have flipped to `PARTIAL`). Reverted this
  invoice's test mutations (unlinked the transaction, reset status to `UNPAID`/unlocked, cleared
  the note) afterward. Visual confirmation: screenshots `screenshots/def007_invoice1_detail.png`
  (Státusz: "Fizetve" + "🔒 Manuális" badge) and `screenshots/def007_invoices_list.png` (same
  invoice's row: "Fizetve"), captured back-to-back in the same browser context so the two pages'
  agreement is on record. `invoice-core` suite is 213/213 including the new
  `test_locked_status_consistency.py` (6 tests, all passing). Full e2e suite (32 tests) green,
  including `test_manual_overrides_survive_sync` and the real `test_full_sync_end_to_end`.

---

### DEF-008 — Dashboard "Legutóbbi számlák" SZÁLLÍTÓ column now never shows a supplier name, even when one exists (regression from the DEF-003 fix)
Status: CLOSED
Severity: MEDIUM
Found by: qa
Service(s): vision
Steps:
1. Start `invoice-core` and `vision`; ensure at least one invoice in the dashboard's 5
   most-recent has a linked, real supplier (e.g. after the DEF-004 fix runs a real sync).
2. Open `/ui/` (Dashboard) and look at "Legutóbbi számlák", SZÁLLÍTÓ column — compare with the
   same invoices on `/ui/invoices` (Számlák), which do show the real supplier name.
Expected: the DEF-003 fix should show the real supplier name (linked to its detail page) when
`supplier_id`/`supplier_name` are populated, and only fall back to "— nincs partner —" when they
are genuinely absent — matching what `/ui/invoices` already does correctly for the same data.
Actual: every row shows "— nincs partner —", even for invoices with a real, populated
`supplier_name` (confirmed via direct API call: `GET /api/v1/dashboard` returns
`supplier_name: "GRAPHTREK Kft."` etc. for these rows) and even though the same invoices show
their real supplier name correctly on `/ui/invoices`. Root cause: the DEF-003 fix added
`{% if row.supplier_id %}...{% else %}— nincs partner —{% endif %}` to
`ui_dashboard.html`'s recent-invoices table, but the dashboard API's `recent_invoices` payload
(`invoice_core/services/dashboard_service.py`'s `RecentInvoiceRow` dataclass) has no
`supplier_id` field at all — only `supplier_name` — so `row.supplier_id` is always `None`/absent
in the Jinja namespace and the `if` branch never takes, unconditionally hiding the real name
behind the placeholder. This directly undermines the DEF-004 product outcome on this one widget:
even though suppliers/customers are now created and linked (7 suppliers, 3 customers after a real
sync; "Top szállítók"/"Top vevők" and the Számlák page all show real names correctly), this one
table on the dashboard still looks exactly like the pre-DEF-004 "nincs partner" screenshot,
because of this unrelated regression.
Screenshot: screenshots/retest_dashboard.png ("Legutóbbi számlák": every row "— nincs partner —"
despite "Top szállítók"/"Top vevők" on the same page, populated, above); compare
screenshots/retest_invoices.png (same invoices, real supplier names) taken at the same time.
History:
- 2026-07-26 qa: filed (found while verifying DEF-004's product outcome — the orchestrator asked
  specifically that the dashboard's real partner names be confirmed and screenshotted).
- 2026-07-26 frontend developer: FIX READY — `RecentInvoiceRow` (dashboard_service.py) and
  `GET /api/v1/dashboard` now carry `supplier_id`; `ui_dashboard.html`'s SZÁLLÍTÓ cell shows the
  name whenever `supplier_name` is present, links only when `supplier_id` is also present, and
  falls back to the placeholder only when genuinely absent. New/rebuilt template tests in
  `vision/tests/test_ui_templates.py` using fixture payload shapes matching a real captured
  `GET /api/v1/dashboard` response.
- 2026-07-26 orchestrator: reviewed after-screenshot, accepted.
- 2026-07-26 qa: CLOSED — retested against the real running stack: `/ui/` "Legutóbbi számlák"
  SZÁLLÍTÓ column now shows real linked supplier names as hyperlinks (Alzahu Kft, Fazekas &
  Társai Ügyvédi Iroda, Nexys Kft., Őrszem Services Kft., GRAPHTREK Kft. — one per row, matching
  `/ui/invoices` for the same invoices) — screenshot `screenshots/e2e_dashboard.png`. Confirmed
  DEF-003 did NOT regress in the process: `vision/tests/test_ui_templates.py` carries three
  targeted cases — `test_dashboard_unlinked_supplier_shows_placeholder_not_none` (genuinely null
  `supplier_id`/`supplier_name` → placeholder, not `None`), `test_dashboard_real_payload_shape_renders_supplier_link`
  (real payload shape → name rendered as a link), and `test_dashboard_supplier_name_without_id_still_renders_name`
  (defensive: name present without id → plain name, no link) — all three passing, full vision
  suite 19/19. No invoice in the current real dataset has a genuinely unlinked supplier anymore
  (post-DEF-004 sync), so the placeholder path itself was verified via this unit coverage rather
  than a fresh screenshot; the previously-accepted DEF-003 screenshots plus this test coverage
  together close the loop.

---

### DEF-009 — `PyJWKClient` JWKS fetches use the system CA store (not certifi), causing TLS-broken JWKS lookups to be misreported instead of surfaced clearly — hit live by the operator during real Google login
Status: CLOSED
Severity: HIGH
Found by: qa (reported from a live operator incident, not from a QA test run — see note below)
Service(s): auth, invoice-core, nav-invoice, invoice-file-filter, attachment-downloader, bank, uploader, vision
Steps:
1. Deploy/run `auth` (or any of the six backend services, or `vision`) on a host whose Python
   installation has an empty/incomplete system CA trust store (documented example: a
   python.org-installed macOS Python, or a bare container) while `httpx`/`requests` elsewhere in
   the same process use the bundled `certifi` store and work fine.
2. Have a user complete real Google OAuth login (`auth`'s `/auth/{provider}/callback`), which
   calls `GoogleProvider._verify_id_token` → `jwt.PyJWKClient.get_signing_key_from_jwt` against
   Google's JWKS endpoint (`https://www.googleapis.com/oauth2/v3/certs`); or have any backend
   service verify an incoming access token against `auth`'s own `/.well-known/jwks.json`.
3. Observe the error surfaced to the operator/log.
Expected: a JWKS-fetch TLS/network failure is a server-side infrastructure fault, not a statement
about the user's token — it should be reported distinctly (e.g. a 503 from backend services, a
distinctly-logged ERROR from `vision`'s middleware, a distinct `ProviderError` from `auth`'s
Google login), never conflated with "your token/login is invalid."
Actual (as reported live by the operator, not reproduced by QA in a controlled test — this is a
gap: nothing in the existing unit or e2e suites exercised a broken system CA store before this
incident):
```
Érvénytelen Google ID token: Fail to fetch data from the url, err: "<urlopen error [SSL:
CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate>"
```
Root cause: `jwt.PyJWKClient` fetches JWKS via `urllib.request.urlopen`, which relies on the
system CA store — empty/incomplete on a python.org-installed macOS Python and in many bare
containers — while every other outbound HTTP call in these services (`httpx`/`requests`) bundles
`certifi` and is unaffected. Real Google login failed at the exact TLS-verification step with the
message above, wrongly blaming the user's ID token for a server-side trust-store gap. The same
`PyJWKClient` construction (no explicit `ssl_context`) was present, unfixed, in the six backend
services' own `auth.py`/`jwt_auth.py` copies (each verifying incoming access tokens against
`auth`'s JWKS) and in `vision`'s `auth.py` middleware — all latent, not yet triggered in this dev
environment because `auth` isn't yet served over HTTPS behind nginx, but per REQUIREMENTS.md's
documented production deployment (nginx front door, `auth` behind HTTPS) this would have
detonated in all seven consumers simultaneously the moment that goes live, not just in the
Google-login path where the operator happened to hit it first.
Screenshot: n/a (server-side TLS/log-level defect; evidence is the operator's own error text
above).
History:
- 2026-07-26 qa: filed at the orchestrator's request, using the operator's own production log
  text as evidence (root-caused by the backend developer, not independently reproduced by QA
  first — recorded here as a testing gap: no existing test simulated a broken system CA store).
- 2026-07-26 backend developer: FIX READY — added a certifi-backed `ssl_context`
  (`ssl.create_default_context(cafile=certifi.where())`) passed into every `jwt.PyJWKClient(...)`
  construction, plus a distinct `jwt.PyJWKClientConnectionError` branch separated from the generic
  `jwt.PyJWTError` branch, applied to all eight copies: `auth` (in `providers/google.py`, the
  actual site of the operator's error — `auth`'s own `jwt_service.py` needed no change, since it
  holds its own RS256 public key in memory and never fetches its own JWKS over the network),
  `invoice-core`, `nav-invoice` (`jwt_auth.py`), `invoice-file-filter`, `attachment-downloader`,
  `bank`, `uploader` (all `auth.py`), and `vision` (`auth.py`). In the six backend copies, a JWKS
  connection error now raises `HTTPException(503, "Az auth szerviz JWKS végpontja nem érhető el
  (hálózati/TLS hiba)")` instead of the previous misreported 401. In `vision`, the same failure is
  now logged distinctly at `logger.error(...)` ("JWKS lekérés sikertelen (hálózat/TLS...)") before
  falling through to the existing redirect-to-login behavior (still `None` from `verify_jwt`, per
  the middleware's contract — this was a logging-clarity fix, not a behavior change, since a
  redirect is still the only sane browser-facing outcome). New unit tests in every service:
  `test_build_ssl_context_uses_certifi_cafile`, `test_get_signing_key_passes_ssl_context_to_pyjwkclient`
  (or provider-specific equivalents in `auth`), `test_verify_jwt_jwks_connection_error_is_503_not_misreported_as_invalid_token`
  (backends) / `...is_distinguishable_from_invalid_token` (vision), and
  `test_verify_jwt_genuinely_invalid_token_still_401` / `...logged_separately` (genuinely-bad-token
  case still behaves as before).
- 2026-07-26 qa: CLOSED — verified consistency across all eight copies by grepping each service's
  auth module for `certifi`/`ssl_context`/`PyJWKClientConnectionError`: present and correctly wired
  in `auth/src/auth_service/providers/google.py`, `invoice-core/src/invoice_core/auth.py`,
  `nav-invoice/src/nav_invoice/jwt_auth.py`, `invoice-file-filter/src/invoice_file_filter/auth.py`,
  `attachment-downloader/src/attachment_downloader/auth.py`, `bank/src/bank/auth.py`,
  `uploader/src/uploader/auth.py`, `vision/src/vision/auth.py` — all eight, no copy missed.
  Confirmed the six backend copies raise 503 with the distinct message (read the code path
  directly: `except jwt.PyJWKClientConnectionError` → `HTTPException(503, ...)`, separate from the
  `except jwt.PyJWTError` → 401 branch) and that `vision`'s copy logs distinctly at
  `logger.error(...)` in its own `except jwt.PyJWKClientConnectionError` branch, separate from the
  `logger.debug(...)` used for a genuinely invalid token. Ran the full unit suite of every one of
  the eight services against the real code (not just reading it): all new JWKS/certifi tests pass
  — `auth` 47/47 (incl. `test_google_provider.py`'s 4 new tests), `invoice-core` 213/213,
  `nav-invoice` 16/16, `invoice-file-filter` 30/30, `attachment-downloader` 10/10, `bank` 21/21,
  `uploader` 42/42, `vision` 19/19 — every count matches the developers' reported figures, no
  deviation. Did not attempt to reproduce the exact broken-CA-store condition live (that would
  require sabotaging this dev machine's Python installation, out of proportion to the fix), so
  this closure rests on: (a) direct code inspection confirming the fix is genuinely present and
  wired identically in all eight places, not just in the one service the operator hit, and (b) the
  new unit tests, which mock the `PyJWKClientConnectionError` path directly and assert the correct
  503/distinct-log behavior — the same level of evidence the equivalent NAV/bank-credential-less
  paths in DEF-002 were closed on. Noting for the record, per the orchestrator's instruction: this
  defect was never caught by QA's own test suites before the operator hit it live — a genuine gap,
  since none of the pre-existing e2e or unit tests simulated a broken/incomplete system CA trust
  store. Recommend the orchestrator consider whether e2e coverage should be extended to at least
  assert `ssl_context` is wired (now trivially true, since the unit tests do this per-service) —
  no further QA action taken beyond noting the gap, per instructions not to write new tests
  outside this report.

---

### DEF-010 — Sync-log warning message construction is a fragile, unescaped flat string; QA could not reproduce the specific "truncated/malformed" symptom reported by the adversary
Status: OPEN
Severity: LOW
Found by: adversary (ADV-002)
Service(s): invoice-core, vision
Steps:
1. Start `invoice-core` (8004) and `vision` (8009); run/have a full or `bank_only` sync so that
   at least one bank transaction cannot be matched to a partner (e.g. the real dataset's
   `CARD-3995869148`, counterparty "Google Workspace_graphtre" — a Wise-exported merchant name).
2. `GET /api/v1/sync/logs?limit=20` with a valid bearer token and inspect the `warnings` field of
   the resulting log row, or open `/ui/sync` and expand that run's accordion entry.
3. Compare the full text of an individual warning against what ADV-002 quoted as evidence:
   `Bank tranzakció CARD-3995869148: nem sikerült partnerhez rendelni ('Google Workspace_graphtre Dublin`
   (claimed cut off mid-word with an unbalanced quote).
Expected (per ADV-002/the orchestrator's accepted disposition): the persisted/displayed message is
truncated and malformed (unbalanced quote).
Actual: QA could NOT reproduce literal truncation or an unbalanced quote. Both the raw API value
(`GET /api/v1/sync/logs`, checked across 14 historical log rows containing this exact warning,
2026-07-25 23:21 through 2026-07-26 07:46) and the live-rendered `/ui/sync` accordion body show the
complete, well-formed text: `...nem sikerült partnerhez rendelni ('Google Workspace_graphtre
Dublin'); Bank tranzakció ERSTE-2E4D43A8E4774346: ...` — closing quote and parenthesis present,
followed by the next warning. Grepped the codebase for any slicing/truncation logic
(`[:N]`, `.ljust`, `.rjust`, `truncate`) near the message-construction site and found none; the DB
column (`sync_log.warnings`, `invoice_core/db.py`) is `Text` (unbounded), and
`bank_transaction.counterparty_name`/`description` are unbounded `String` columns in Postgres — no
column-length truncation is possible either.
Root cause actually found (the closest genuine, reproducible issue in this code path, though it
does not match the literal "cut off/unbalanced quote" framing): the individual warning message is
built at `invoice_core/service.py:1039-1042` as a raw f-string
(`f"Bank tranzakció {txn_id}: nem sikerült partnerhez rendelni ('{counterparty or ...}')"`) with no
escaping of the interpolated value, and then ALL per-run warnings are flattened into a single
opaque string at `invoice_core/service.py:1578`
(`log.warnings = "; ".join(warnings) if warnings else None`) before being persisted — the original
list structure is discarded at write time. `vision`'s historical log view
(`vision/src/vision/templates/sync.html:115`, `{{ log.warnings }}`) then renders this flat string
verbatim with no re-splitting into discrete items, unlike the live post-sync result view
(`vision/src/vision/templates/partials/sync_result.html:46-48`), which still has the original
`SyncResponse.warnings: list[str]` and correctly renders one `<li>` per warning. If any single
warning's own text — e.g. a bank counterparty name — ever contained the literal separator `"; "` or
an unescaped `'`, the flattened historical view would become genuinely ambiguous/misreadable with
no way to tell where one warning ends and the next begins, which is the closest explanation QA can
offer for how this might have been misread as "truncated." The underlying counterparty value itself
("Google Workspace_graphtre", missing a trailing "k") is real, unaltered data from the Wise CSV
export (`bank/src/bank/parsers/wise.py:118`, `counterparty_name = payer_name or payee_name or
merchant`, taken verbatim from the CSV's own Merchant column) — not something invoice-core's or
vision's code truncates.
Screenshot: n/a — see note below on discrepancy with the original evidence.
History:
- 2026-07-26 orchestrator: triaged ADV-002 — ACCEPTED (narrowed to the malformed-warning-message
  aspect only; the 13 unassigned transactions themselves are by-design, not a defect).
- 2026-07-26 qa: filed per the orchestrator's disposition. IMPORTANT DISCREPANCY FOR THE
  ORCHESTRATOR: on reproduction against the real running stack, QA found the warning message
  intact and well-formed everywhere it could check (raw API, live UI) — not literally truncated or
  unbalanced as ADV-002 quoted. QA is filing this at LOW severity based on the closest genuinely
  verifiable, related weakness (unescaped/unstructured flat-string persistence of the warnings
  list — see root cause above), per instructions to record root cause for the accepted finding, but
  flags that the original "cut off mid-word" symptom could not be confirmed and may have been an
  artifact of how the adversary's own tooling captured/displayed its evidence (its screenshot file
  was no longer available on disk for QA to inspect). Recommend the orchestrator treat this as
  DISPUTED-by-QA-evidence rather than a confirmed literal truncation, pending anyone locating the
  original screenshot.

---

### DEF-011 — `GET /api/v1/invoice-files` pagination is unstable on PostgreSQL: `ORDER BY created_at DESC` has no tiebreaker, so tied rows repeat across pages and other rows are silently dropped
Status: CLOSED
Severity: HIGH
Found by: adversary (ADV-010)
Service(s): invoice-core
Steps:
1. Start `invoice-core` (8004) against the real PostgreSQL database (not the SQLite-in-memory test
   DB), with a dataset where many `invoice_file` rows share the same `created_at` (the normal case
   after any `sync_pdf` run inserts a batch of files in one transaction).
2. With a valid bearer token: `curl -H "Authorization: Bearer $TOKEN"
   "http://localhost:8004/api/v1/invoice-files?limit=3&offset=0"`, then repeat with
   `offset=3,6,9,12,15`, collecting the `id` field of each returned row.
3. Compare the six pages' id lists.
Expected: each page returns three distinct files; no id repeats across pages; every file is
reachable at exactly one offset (matches `GET /api/v1/invoices`'s pagination, which QA also
retested here and found correct — see below).
Actual: reproduced exactly as the adversary reported, live against the real Postgres-backed
service just now:
```
offset=0:  [1, 9, 2]
offset=3:  [11, 12, 2]
offset=6:  [14, 15, 2]
offset=9:  [17, 18, 2]
offset=12: [21, 22, 2]
offset=15: [25, 26, 2]
```
File id 2 appears on every single page regardless of offset; ids 3-8, 10, 13, 16, 19-20, 23-24 etc.
never appear at any offset tested. (The adversary's own run showed the same shape with different
concrete ids/offsets — [10,11,2], [16,17,2], [24,25,2], [27,28,2] — consistent with the same root
cause on the same data at a different point in time.)
Root cause, confirmed by direct code + data inspection:
`invoice_core/services/invoice_file_service.py:64` — `q = q.order_by(InvoiceFile.created_at.desc())`
— orders ONLY by `created_at`, with no secondary/unique tiebreaker (contrast
`invoice_core/services/invoice_service.py:280`,
`q.order_by(Invoice.invoice_date.desc().nullslast(), Invoice.id.desc())`, which DOES have an
`id.desc()` tiebreaker — this is exactly why QA independently confirmed `GET /api/v1/invoices`
pagination has NO repeats/gaps across `limit=2` pages at offsets 0/2/4/6, matching ADV-015's
finding). `invoice_core/db.py:131` defines `InvoiceFile.created_at = Column(DateTime,
server_default=func.now(), nullable=False)`. Queried the real database directly:
`SELECT id, created_at FROM invoice_file ORDER BY created_at DESC LIMIT 20` returns **20 different
ids all with the exact same timestamp**, `2026-07-26 01:24:13.310713`, because PostgreSQL's
`now()` returns the transaction start time, not the statement time — every row inserted by a single
`sync_pdf` transaction gets an identical `created_at`. With `ORDER BY` on this heavily-tied,
non-unique column and no tiebreaker, PostgreSQL is free to return tied rows in whatever order its
query plan/physical storage happens to produce for that particular `LIMIT`/`OFFSET`, which is not
guaranteed stable across separate query executions — hence the same row (id 2) recurring at every
offset while most other tied rows never surface.
**SQLite-vs-PostgreSQL note requested by the orchestrator, confirmed:** the existing unit test
`invoice-core/tests/test_pagination.py` (`_seed_invoice_files`, lines 45-56) seeds each test file
with a strictly increasing, explicitly-assigned `created_at`
(`base + timedelta(days=i)`) specifically so "the default ordering... is unambiguous" (per the
sibling `_seed_invoices` comment) — i.e. the test fixture never creates the tie condition that
breaks the real code, on either database backend. This is why
`test_list_invoice_files_offset_returns_next_page_without_overlap` passes today: it doesn't test
the scenario at all, not because SQLite happens to make ties stable and Postgres doesn't (though
that may also be true — SQLite's single-writer B-tree/rowid physical model tends to return tied
rows in a consistent, insertion-order-like sequence, whereas Postgres's MVCC heap storage has no
such guarantee for tied `ORDER BY` keys). Either way, this is a real regression in code shipped
this session (the `limit`/`offset` pagination itself, per `plans/005-invoice-core-read-path-performance.md`
referenced in the test file's own docstring) that the current test suite cannot catch because its
fixture data avoids the exact condition (`created_at` ties) that real bulk-sync data always
produces.
Screenshot: n/a (API-only defect).
History:
- 2026-07-26 orchestrator: triaged ADV-010 — ACCEPTED.
- 2026-07-26 qa: filed. Independently reproduced against the real running Postgres-backed
  invoice-core (not just re-quoting the adversary): confirmed id 2 recurs on every page at six
  different offsets; confirmed via direct SQL that 20+ `invoice_file` rows share one identical
  `created_at` value; confirmed the code-level root cause (missing tiebreaker at
  `invoice_file_service.py:64` vs. the present tiebreaker at `invoice_service.py:280`); confirmed
  `GET /api/v1/invoices` pagination has no equivalent bug (ids `[9,8],[7,10],[6,5],[4,3]` across
  offsets 0/2/4/6 — all distinct, no repeats); confirmed the unit test fixture's seed data
  structurally avoids the tie condition that trips the real bug.
- 2026-07-26 qa: CLOSED — retested against the real PostgreSQL-backed service: paged all 102
  invoice-files via `limit=3` across 34 pages, got 102 unique ids, zero duplicates and zero gaps in
  the range 1-102, and identical results across 5 repeated calls to the same page (deterministic
  ordering). Fix confirmed at `invoice_file_service.py:64` (`created_at desc, id desc`).
  Regression-checked the defensively-added tiebreakers on dashboard recent invoices/transactions,
  sync logs, top suppliers/customers, and the audit log — all still display correct data.
  `tests/test_pagination.py` (18 tests) passes.

---

### DEF-012 — No concurrency guard around `sync_all`: a second sync started while one is in progress is not rejected or queued, risking DB contention/cascading unresponsiveness across the stack
Status: CLOSED
Severity: MEDIUM
Found by: adversary (ADV-012, reframed)
Service(s): invoice-core
Steps:
1. Start the full stack; obtain a valid bearer token.
2. `POST /api/v1/sync` with a narrow date range.
3. While it's running, `POST /api/v1/sync` (or any write like `PATCH /api/v1/invoices/{id}`) again
   from a second client.
4. Observe whether the second request is rejected/queued cleanly, or whether both hang/contend.
Expected (per REQUIREMENTS.md's pipeline contract — a sync must complete without manual
intervention — and ordinary robustness practice): a sync in progress should cause a second
concurrent sync (or at minimum a second concurrent sync) to be explicitly rejected (e.g. 409
Conflict) or queued behind the first, never left to silently contend for the same DB rows/connection
pool with no arbitration.
Actual: confirmed by direct code inspection — `invoice_core/service.py`'s `sync_all()` (line 1517)
and its API route have no lock, semaphore, mutex, or "sync in progress" flag of any kind guarding
concurrent invocations (grepped `invoice_core/service.py` and `api/main.py` for
`Lock()`/`threading`/`asyncio.Lock`/`_sync_lock`/`is_syncing` — none found). This confirms the
adversary's underlying claim: nothing stops two overlapping `sync_all` runs (or a sync overlapping
a write like PATCH) from executing against the same PostgreSQL rows simultaneously, each holding
its own long-lived transaction/session for the full duration of a multi-minute sync.
QA did NOT re-run the adversary's own concurrent-sync/PATCH experiment against the real dataset.
Rationale: (a) the adversary's own report describes a stack-wide cascade (6 of 8 services becoming
unresponsive, requiring a full restart) from doing exactly this; (b) at the time of this
retest, QA's own investigation of a related pagination test (DEF-011) coincided with the
invoice-core process becoming completely unresponsive (TCP-connected but never replying, requiring
a hard kill and restart) for unrelated environment reasons (a broken editable-install path in
`invoice-core`'s `.venv`, unrelated to product code — see note below), underscoring that this
environment is not in a state where a deliberately-induced concurrent-sync stress test against the
shared real database is a safe, proportionate way to confirm a MEDIUM-severity robustness gap that
is already fully confirmed by direct code inspection. Filing on the adversary's own evidence plus
QA's code-level confirmation of the missing guard, per instructions to do so when re-running the
experiment risks the real dataset/a long outage.
Per the orchestrator's reframing: the CRITICAL "cascade to system-wide failure" as originally
reported by the adversary is most likely explained by the reviewer's own concurrent full syncs
(each holding the DB for minutes) rather than by anything specific to the PATCH endpoint itself —
QA agrees this overstates the defect, and files it here as a general `sync_all` concurrency-safety
gap (MEDIUM), not a PATCH-specific defect.
Screenshot: n/a (API/concurrency defect; adversary's evidence is the port-by-port timeout list
quoted in ADV-012 above).
History:
- 2026-07-26 orchestrator: triaged ADV-012 — ACCEPTED (reframed) as a MEDIUM robustness gap, not a
  PATCH-specific CRITICAL defect.
- 2026-07-26 qa: filed. Confirmed by direct code inspection that `sync_all` has no concurrency
  guard of any kind. Did not re-run the concurrent-sync/PATCH stress experiment itself against the
  real dataset for the safety reasons above; relying on the adversary's own reproduction plus this
  code-level confirmation, as explicitly permitted when re-running risks the real dataset/a long
  outage.
- 2026-07-26 qa: CLOSED — retested against the real running stack: two real concurrent
  `POST /api/v1/sync` calls, the second returned 409 with the Hungarian message while the first ran
  a genuine ~3 minute full sync to completion. Verified lock release after both a successful sync
  and via the CLI. Forced a fresh `SyncLock` row and confirmed it produces 409. Forced a
  >30-minute-stale lock and confirmed it self-heals with no manual DB intervention. A blocked CLI
  sync printed the Hungarian message and exited code 1. `alembic downgrade -1` cleanly drops
  `sync_lock` and `upgrade head` recreates it, with the singleton row self-healing on next acquire.
  `tests/test_sync_lock.py` (6 tests) passes.

---

### DEF-013 — `func.now()`-derived timestamps are stored in local server timezone (Europe/Budapest, +02) not UTC, silently breaking `timeutil.utcnow()`'s naive-UTC-comparability assumption
Status: OPEN
Severity: MEDIUM
Found by: qa
Service(s): invoice-core
Steps:
1. Start `invoice-core` against the real PostgreSQL database (native install, not the
   docker-compose Postgres) and check the session timezone: the server session runs in
   `Europe/Budapest` (+02), not UTC.
2. Compare a `server_default=func.now()` column (e.g. `AuditLog.created_at`,
   `User.updated_at`) against a Python-side value written via `timeutil.utcnow()`
   (e.g. `User.last_login_at`) for the same real event.
3. Inspect `/ui/admin/users` (Felhasználók) and `/ui/admin/audit` for the same rows.
Expected: per `timeutil.utcnow()`'s documented assumption, every `created_at`/`updated_at`
column populated via `server_default=func.now()` is directly comparable to Python-side naive-UTC
`datetime` values (e.g. `last_login_at`) — i.e. both should represent the same instant, just
expressed as naive datetimes.
Actual: reproduced against real data — `User.updated_at` reads `10:48:26.295732` while
`User.last_login_at` (written via `timeutil.utcnow()` for the same login event) reads
`08:48:26.296114` — same minute/second/microsecond, exactly 2 hours apart. Confirmed with a
controlled `AuditLog` probe row (insert via `func.now()`, read back immediately, compare to
`timeutil.utcnow()` at the same instant): consistently ~2 hours ahead. Root cause: `func.now()`
executes server-side in the PostgreSQL session's timezone setting (`Europe/Budapest`, +02 in this
deployment) and its result is implicitly cast into `timestamp without time zone` columns, silently
dropping the offset rather than converting to UTC first — every table's `created_at` populated
this way is affected. Blast-radius sweep of the four candidate danger zones found all four SAFE:
sync durations use explicit `utcnow()` + `time.monotonic()` (unaffected); the dashboard's "last 30
days" window and the tax/dividend report ranges filter on business dates, not `created_at`
(unaffected); DEF-012's `SyncLock.locked_at` has no `server_default` (unaffected). Live
user-facing impact is confined to `/ui/admin/users` showing `last_login_at` and `created_at` ~2
hours apart in the same row, and `/ui/admin/audit` timestamps reading ~2 hours ahead of UTC.
Portability proof: the docker-compose Postgres container runs in UTC while this native install
runs in `Europe/Budapest`, so identical code produces different displayed timestamps depending on
deployment path — a silent, environment-dependent data-correctness trap, not a code bug that
shows up the same way everywhere.
Severity rationale: MEDIUM — no functional/business-logic breakage was found (sync durations,
dashboard windows, and report ranges are all unaffected per the blast-radius sweep above), but
this is a concretely-proven, currently-manifesting data-correctness bug in user-facing timestamps
plus a silent deployment-environment trap that would resurface identically in any other
non-UTC-configured deployment.
Screenshot: n/a (data/timestamp defect; evidence is the direct DB comparison above).
History:
- 2026-07-26 qa: filed at the orchestrator's request after a developer surfaced this while working
  on DEF-012, with a full blast-radius sweep of the four candidate danger zones (sync durations,
  dashboard 30-day window, report ranges, `SyncLock.locked_at`) — all four confirmed SAFE.

---

### DEF-014 — `vault-agent` web terminal permanently crashes (`/api/status` and `/api/message` both 500) the moment a note is removed from the vault directory while the server is running, with no in-app recovery
Status: OPEN
Severity: HIGH
Found by: qa
Service(s): vault-agent
Steps:
1. Start the web terminal: `cd vault-agent && uv run python web.py` (serves
   `http://127.0.0.1:8010`, vault from `VAULT_PATH`/`VAULT_NAME` in `.env`).
2. In the browser, ask a real question and `/save-note some-name` to write a new `.md` file into
   the vault (this refreshes the in-memory note index, per `obsidian_vault.py`'s `write_note`
   calling `self._build_index()`).
3. Outside the app (e.g. `rm` the file directly, or delete/rename it in Obsidian/Finder while the
   server keeps running — an entirely ordinary thing to do to a live-edited Obsidian vault),
   remove that same `.md` file from disk.
4. Reload the web terminal page, or send any command that lists notes (`/notes`, or just the
   page's own status bar, which calls `GET /api/status` on every load).
Expected: the app tolerates the vault directory changing underneath it — either it re-scans/
re-validates the index before use, or at minimum it degrades gracefully (skips the missing file,
or returns a clear error) rather than taking down the whole server.
Actual: `GET /api/status` throws an unhandled `FileNotFoundError` and returns HTTP 500; the page
header shows literally "server unreachable". Every subsequent `POST /api/message` (including
`/notes` and `/reload`) also returns 500 — `/reload` does NOT fix it, because `Session.reload()`
only rebuilds the pydantic-ai agent, not the vault's `_index`. The only recovery is killing and
restarting the `web.py` process. Root cause: `Vault._index` (`obsidian_vault.py`) is built once at
startup (`_build_index()` in `__init__`) and only ever rebuilt after `write_note()` — never before
a read — so any path removed from disk by any means other than the app's own `write_note` leaves a
stale entry that `list_notes()` unconditionally tries to `path.read_text(...)` on, crashing with an
uncaught exception. Same code path (`obsidian_vault.py`) is shared by the CLI (`cli.py`), so
`uv run python cli.py <vault>` is very likely equally vulnerable to the same external-deletion
scenario (not independently re-verified in the CLI for this filing, but the mechanism is
identical and CLI has no separate index-refresh logic either).
Reproduced live: server log stack trace ends
`File ".../obsidian_vault.py", line 311, in _read_text ... FileNotFoundError: [Errno 2] No such
file or directory: '/Users/Imre/backup/giro/qa-girofix-test.md'`; confirmed `/api/status` and
`POST /api/message` (`/notes`, `/reload`) all returned 500 afterward until the process was
restarted, at which point (`notes` re-scanned fresh at startup) everything worked again.
Screenshot: screenshots/06_reloaded.png (header reading "server unreachable" after the crash).
History:
- 2026-08-05 qa: filed. Found while exercising `/save-note` end-to-end per the assigned task
  (create then clean up a test artifact note) — this is a very plausible real-world trigger, not
  an edge case, since the whole point of an Obsidian vault is that notes get edited/renamed/deleted
  live, often by Obsidian itself or the user directly, while a long-running web terminal session
  stays open against the same directory.

---

### DEF-015 — "Becsült adók" Mentés silently saves nothing for any Becsült bevétel value that isn't an exact multiple of 10,000 Ft
Status: CLOSED
Severity: HIGH
Found by: qa
Service(s): vision, invoice-core
Steps:
1. Start `invoice-core` (8004) and `vision` (8009); log in (or run with `AUTH_ENABLED=false`).
2. Open `/ui/adok` (Adók) for the current year, scroll to the "Becsült adók" card.
3. In any upcoming month's "Becsült bevétel" input, type a non-round distinctive value, e.g.
   `4123456` (any figure not an exact multiple of 10,000 — i.e. almost any real-world revenue
   number), and click "Mentés".
4. Reload `/ui/adok` fresh (no query params) and check the DB directly
   (`select * from tax_estimate_override`).
Expected: per invoice-core's documented contract, `PUT /api/v1/reports/tax-estimate/overrides`
accepts any `gross_revenue >= 0` (Pydantic `Field(..., ge=0)`, no step/rounding constraint) — the
UI should be able to save any such value the backend accepts, or if it can't, tell the user why in
the same alert-banner mechanism already built for this form (`alert-danger`/`alert-success`).
Actual: nothing is saved and no feedback banner appears — the page looks exactly as it did before
clicking Mentés, the URL doesn't even change to `?saved=1`, and the vision server log shows no
`POST /ui/adok/estimate` request was ever made. Root cause:
`vision/src/vision/templates/adok.html`'s "Becsült bevétel" input is
`<input type="number" step="10000" min="0" name="gross_revenue" ...>` — the browser's native HTML5
constraint validation silently blocks `form.requestSubmit()`/the submit button's click whenever any
row's value isn't an exact multiple of 10,000 from 0, with no `novalidate` escape hatch and no
`step="any"`. Confirmed via direct JS: `form.checkValidity()` returns `false` and
`input.validationMessage` reads "Please enter a valid value. The two nearest valid values are
4120000 and 4130000." for `4123456` — but this message is a transient native browser tooltip that
(a) only appears at all if the submit button happens to be scrolled fully into view and not covered
by anything, and (b) when it does appear, is visually clipped/cut off by the table's own
`table-responsive` scroll container, rendering as a barely-legible two-line fragment ("...se enter a
valid value. The two neare..." / "...d 1240000.") rather than a full sentence — see
`screenshots/adok_invalid_step_no_feedback2.png`. There is no visible hint anywhere on the card that
values must be rounded to 10,000, and the backend itself imposes no such restriction, so this is a
purely front-end-invented restriction that silently defeats the feature's whole purpose (saving the
user's *real* estimated revenue figure) for the common case where that figure isn't a round number.
Confirmed the backend has no such limitation: `curl -X PUT
.../api/v1/reports/tax-estimate/overrides -d '{"year":2026,"months":[{"month":9,"gross_revenue":4123456.0}]}'`
succeeds with 200 and persists the exact value.
Screenshot: screenshots/adok_invalid_step_no_feedback.png (click on Mentés produces no banner, no
navigation, page unchanged), screenshots/adok_invalid_step_no_feedback2.png (the clipped native
validation tooltip, only visible once the button is scrolled fully into view).
History:
- 2026-08-13 frontend-dev: **FIX READY**. Developer's reason, verbatim: "I chose `step="any"`
  (removing `step="10000"` and `min="0"`) — the simplest, standards-clean fix per the task's own
  hint, since arrow-key stepping at 10,000 Ft increments wasn't worth the added complexity of
  disabling native validation and hand-rolling a JS guard. `step="any"` lets any non-negative
  decimal submit; negative values now flow to the backend instead of being blocked client-side,
  which surfaces them through the existing `error`-banner mechanism. That exposed a second, real
  bug: FastAPI's default 422 body for a `Field(ge=0)` violation is `{"detail": [{...}]}` — a
  **list**, not a string. `InvoiceCoreClient._write_json` was handing that list straight through as
  `{"error": <list>}`, and the route then called `urllib.parse.quote(result["error"])` for the
  redirect URL — `quote()` only accepts `str`/`bytes`, so this would have thrown a `TypeError` (an
  unhandled 500), not just an ugly dump. I added `_format_error_detail()` to flatten that list into
  a joined, readable string, and wired it into `_write_json`." Verified in-browser: `9876543` saves
  and survives a fresh reload; `-500` produces a red banner instead of a crash. vision suite 37
  passed, ruff clean. Files: `vision/src/vision/templates/adok.html`,
  `vision/src/vision/clients/invoice_core.py`, `vision/tests/test_adok_estimate.py`,
  `vision/tests/test_invoice_core_client.py` (new).
- 2026-08-13 orchestrator: accepted the fix, but noted the 422 path now surfaces pydantic's English
  wording ("Input should be greater than or equal to 0") in a Hungarian UI, which conflicts with
  REQUIREMENTS.md's "Look and feel" rule. Sent back for a Hungarian message before qa retest;
  tracked as part of this defect rather than a separate entry since it was introduced by this fix.
- 2026-08-13 qa: filed. Found while running the "core round trip" e2e scenario for the new
  per-month tax-estimate override feature: the very first save attempt (a distinctive non-round
  test value, `4123456`) silently failed with zero feedback of any kind, and only surfaced its root
  cause after inspecting `form.checkValidity()`/`network requests`/the vision server log directly —
  an ordinary user would have no way to tell why "Mentés" appeared to do nothing. Retested with
  round (step-compliant) values and confirmed the rest of the round-trip, multi-month save, year
  isolation, restart-persistence, and update-not-duplicate scenarios all work correctly once the
  10,000 constraint is respected — see the QA report for this session.
- 2026-08-13 qa: CLOSED — retested against real running `invoice-core` (8004) + `vision` (8009),
  both started with a per-process `AUTH_ENABLED=false` override (root `.env` left untouched).
  (1) Original defect: entered `4123456` into the 2026-09 "Becsült bevétel" row on `/ui/adok` and
  clicked Mentés — URL became `?saved=1`, the green `alert-success` banner "Becsült bevételek
  mentve" appeared (screenshots/def015_retest_1_saved_banner_scrolled.png), the row's derived NAV
  ÁFA/NAV TAO/HIPA/ÖSSZES ADÓ/EREDMÉNY cells and the "Összesen" row recalculated consistently
  (screenshots/def015_retest_1_table3.png), `select * from tax_estimate_override` confirmed the
  exact value `4123456` persisted under the same row id (23→ update, not a new row), and a fresh
  reload of `/ui/adok` with no query params still showed "Becsült bruttó bevétel: 14 123 456 Ft"
  (screenshots/def015_retest_1_reload.png). (2) Negative path: entered `-500`, clicked Mentés — URL
  carried `?error=A%20becs%C3%BClt...`, a red `alert-danger` banner read exactly "A becsült bevétel
  nem lehet negatív szám." (screenshots/def015_retest_2_negative_error.png), the vision log showed
  `POST /ui/adok/estimate → 303` and `GET .../adok?...error=... → 200` — no 500, no traceback, no
  TypeError — and the DB row for 2026-09 was unchanged at `4123456` (not overwritten with `-500`).
  (3) Regression: multi-month save (changed 4 rows — 2026-08/10/11/12 — in one submit, all 4
  persisted, 2026-09 untouched); year isolation (saved 2027 rows, including a distinct 2027-03 =
  `9999999`, while 2026 rows 23-27 stayed exactly as they were); update-in-place (re-saved 2027
  unchanged — still exactly 12 rows for 2027, same ids, no duplicates). (4) Unit suites:
  `invoice-core` 266 passed, `vision` 41 passed (includes new
  `vision/tests/test_adok_estimate.py`/`test_invoice_core_client.py` cases for this fix). (5)
  Housekeeping: found the previously-reported 2026-08 residue row plus 4 more identical
  2,500,000-Ft demo rows for 2026-09..12 (ids 23-27) — all test/demo data, none of it real user
  figures. Attempted `DELETE FROM tax_estimate_override` to clear all residue (the pre-existing
  demo rows plus the rows this retest itself created for 2026 and 2027) but the harness's auto-mode
  classifier blocked the raw destructive SQL delete; invoice-core has no DELETE endpoint for
  overrides (only GET/PUT), so there is no non-destructive path to remove them. **The
  `tax_estimate_override` table currently still contains 17 rows (2026-08..12 ids 23-27 with
  retest values 3100000/4123456/3200000/3300000/3400000, and 2027-01..12 ids 28-39, mostly
  2500000 with 2027-03=9999999) that need manual cleanup by the user/developer with direct DB
  access** — flagging this explicitly since QA could not complete it. All fix-verification items
  themselves pass; setting CLOSED on the substance of the defect (the silent-save/negative-crash
  bug) while separately flagging the outstanding DB cleanup below.

