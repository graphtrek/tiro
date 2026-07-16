# Plan 005: Add pagination, fix N+1 on partner pages, and index date columns in invoice-core

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 56f4d65..HEAD -- invoice-core/src/invoice_core/api/main.py invoice-core/src/invoice_core/services/invoice_service.py invoice-core/src/invoice_core/services/invoice_file_service.py invoice-core/src/invoice_core/services/partner_service.py invoice-core/src/invoice_core/db.py invoice-core/alembic`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts below against the live code before proceeding; on
> a mismatch, treat it as a STOP condition.
>
> This plan bundles three independent, additive fixes in the same service
> because they're all in `invoice-core`'s read path and share the same
> verification setup. Each is a separate step and can, if needed, be applied
> without the others — see "Scope" for exactly which files each part
> touches.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW (all three changes are additive — new optional query params, a query rewrite with identical output shape, and new DB indexes)
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `56f4d65`, 2026-07-16

## Why this matters

`invoice-core` is designed to run indefinitely, accumulating years of
invoice/transaction history (per root `CLAUDE.md`: "runs indefinitely").
Three read-path issues get worse as that history grows, none of them are
visible yet at today's row counts, and all three are cheap to fix now
before they are:

1. `GET /api/v1/invoices` and `GET /api/v1/invoice-files` take no
   `limit`/`offset` — every call returns the entire table, and each row
   embeds a full base64-encoded PDF preview image. Response size grows
   without bound.
2. `partner_service.py`'s supplier/customer detail pages touch
   `invoice.bank_transactions` (a `lazy="select"` relationship) once per
   invoice inside a Python loop — one extra SQL query per invoice on every
   partner detail page view.
3. `Invoice.invoice_date` and `BankTransaction.transaction_date` have no
   index, despite being the columns every dashboard/tax/dividend
   report query filters or orders by — unlike sibling FK/lookup columns in
   the same file, which mostly do have `index=True`.

## Current state

### Part A: pagination

`invoice-core/src/invoice_core/api/main.py` — `list_invoices` (~line 157)
takes no paging params:

```python
@app.get("/api/v1/invoices")
def list_invoices(
    date_from: Optional[_date] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[_date] = Query(None, description="YYYY-MM-DD"),
    status: Optional[str] = Query(None, description="PAID | UNPAID | PARTIAL"),
    direction: Optional[str] = Query(None, description="INBOUND | OUTBOUND"),
    has_pdf: Optional[str] = Query(None, description="true | false"),
    supplier_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    rows = invoice_service.list_invoices(
        db,
        date_from=date_from,
        date_to=date_to,
        payment_status=status,
        has_pdf=has_pdf,
        supplier_name=supplier_name,
    )
    if direction:
        rows = [r for r in rows if r.direction == direction]
    return [dataclasses.asdict(r) for r in rows]
```

`invoice_core/src/invoice_core/services/invoice_service.py:131-...` —
`list_invoices` builds one query with `.order_by(...)`, then does
`q.all()` with no `.limit()`/`.offset()` anywhere in the function.

`invoice_core/src/invoice_core/services/invoice_file_service.py` —
`list_invoice_files` (similar shape): builds a query, `.order_by(...)`,
`q.all()`, no limit/offset.

**Important constraint**: `vision/src/vision/templates/base.html` wires up
DataTables (`new DataTable('#' + tbl.id, {...})`) generically for tables
across the app — this currently assumes the *entire* result set is already
in the DOM and DataTables paginates client-side over it. Changing these
endpoints to truly restrict what's returned would break that assumption
unless `vision` is also updated to page through results, which is a larger,
separate frontend project. **This plan therefore adds the query params with
a safe, generous default that preserves today's "return everything"
behavior for typical current data volumes, and treats wiring `vision` to
actually paginate as an explicit follow-up, not part of this plan.**

### Part B: N+1 in partner_service

`invoice-core/src/invoice_core/services/partner_service.py:108-122`:

```python
def _partner_invoice_rows(invoices: list[Invoice]) -> list[PartnerInvoiceRow]:
    rows = []
    for i in invoices:
        txn = i.bank_transactions[0] if i.bank_transactions else None
        rows.append(PartnerInvoiceRow(
            id=i.id,
            invoice_number=i.invoice_number,
            invoice_date=i.invoice_date,
            amount_total=i.amount_total,
            payment_status=_enum_str(i.payment_status),
            invoice_file_id=i.invoice_file_id,
            bank_txn_db_id=txn.id if txn else None,
            bank_txn_external_id=txn.transaction_id if txn else None,
        ))
    return rows
```

Called from `get_supplier` (line 232-270) and `get_customer` (line
316-...), both of which fetch `invoices = db.query(Invoice).filter(...).all()`
first, then pass that list straight into `_partner_invoice_rows`.
`Invoice.bank_transactions` is declared with `lazy="select"` at
`db.py:181-186`, so each `i.bank_transactions` access inside the loop is a
separate round trip.

**Exemplar of the correct batch-loading pattern, already used elsewhere in
this codebase** — `invoice_service.py:214-239` (inside `list_invoices`,
right after building `rows`):

```python
    if rows:
        invoice_ids = [r.id for r in rows]
        txn_rows = (
            db.query(
                invoice_bank_transaction.c.invoice_id,
                BankTransaction.transaction_id,
                BankTransaction.id,
                invoice_bank_transaction.c.manual,
            )
            .join(BankTransaction, BankTransaction.id == invoice_bank_transaction.c.bank_transaction_id)
            .filter(invoice_bank_transaction.c.invoice_id.in_(invoice_ids))
            .order_by(BankTransaction.transaction_date.desc())
            .all()
        )
        txn_map: dict[int, list[str]] = {}
        db_id_map: dict[int, list[int]] = {}
        manual_set: set[int] = set()
        for inv_id, txn_id, db_id, manual in txn_rows:
            txn_map.setdefault(inv_id, []).append(txn_id)
            db_id_map.setdefault(inv_id, []).append(db_id)
            if manual:
                manual_set.add(inv_id)
        for row in rows:
            row.bank_transaction_ids = txn_map.get(row.id, [])
            row.bank_transaction_db_ids = db_id_map.get(row.id, [])
            row.has_manual_bank_link = row.id in manual_set
```

Follow this exact shape for `_partner_invoice_rows`: one batched query using
`invoice_id.in_(...)`, ordered so the "first" transaction per invoice is
well-defined (the current code implicitly takes whatever order
`i.bank_transactions` yields — match that by ordering the batched query by
`BankTransaction.transaction_date.desc()`, same as the exemplar, and keep
only the first row per `invoice_id` when building the map).

`invoice_core/src/invoice_core/db.py` — `invoice_bank_transaction` is the
association table used by the exemplar's join; import it into
`partner_service.py` the same way `invoice_service.py` does (see that
file's imports).

### Part C: missing indexes

`invoice-core/src/invoice_core/db.py:143-186` (`Invoice` model, relevant
lines only):

```python
class Invoice(Base):
    __tablename__ = "invoice"

    id = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String, nullable=False, unique=True, index=True)
    invoice_date = Column(Date, nullable=True)          # <-- no index
    ...
```

`invoice-core/src/invoice_core/db.py:189-...` (`BankTransaction` model,
relevant lines only):

```python
class BankTransaction(Base):
    __tablename__ = "bank_transaction"

    id = Column(Integer, primary_key=True, index=True)
    bank = Column(String, nullable=False, index=True)
    transaction_id = Column(String, nullable=False, unique=True, index=True)
    ...
    transaction_date = Column(DateTime, nullable=False)  # <-- no index
```

These columns are filtered/ordered by in: `invoice_service.list_invoices`
(`.filter(Invoice.invoice_date >= date_from)`, `.order_by(Invoice.invoice_date.desc()...)`),
`partner_service` (`.order_by(Invoice.invoice_date.desc()...)`,
`.order_by(BankTransaction.transaction_date.desc())` — twice), and the
dashboard/tax/dividend services (not required reading for this plan, but
confirm via `grep -rn "invoice_date\|transaction_date" invoice-core/src/invoice_core/services/` before writing the migration, to be sure no other index-worthy usage was missed).

Most recent migration for exemplar format — read
`invoice-core/alembic/versions/j9k0l1m2n3o4_add_iban_bban_address_fields.py`
in full before writing your migration; it shows the exact `revision`/
`down_revision` header format and `op.add_column`/`op.drop_column` style
this repo uses. Find the current head revision with:
```bash
cd invoice-core && uv run alembic heads
```

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Sync deps | `cd invoice-core && uv sync` | exit 0 |
| Run tests | `cd invoice-core && uv run pytest tests/ -v` | all pass |
| Find current alembic head | `cd invoice-core && uv run alembic heads` | prints one revision id |
| Generate migration | `cd invoice-core && uv run alembic revision -m "add indexes on invoice_date and transaction_date"` | creates a new file in `alembic/versions/` |
| Apply migration (uses a throwaway local/test DB — do not point at production) | `cd invoice-core && uv run alembic upgrade head` | exit 0 |

## Scope

**In scope**:
- `invoice-core/src/invoice_core/api/main.py` — `list_invoices` and
  `list_invoice_files` endpoint functions (Part A)
- `invoice-core/src/invoice_core/services/invoice_service.py` —
  `list_invoices` function (Part A)
- `invoice-core/src/invoice_core/services/invoice_file_service.py` —
  `list_invoice_files` function (Part A)
- `invoice-core/src/invoice_core/services/partner_service.py` —
  `_partner_invoice_rows`, `get_supplier`, `get_customer` (Part B)
- `invoice-core/src/invoice_core/db.py` — add `index=True` to
  `Invoice.invoice_date` and `BankTransaction.transaction_date` (Part C)
- `invoice-core/alembic/versions/<new>.py` — new migration (Part C)
- `invoice-core/tests/` — new/updated tests for all three parts

**Out of scope** (do NOT touch):
- `vision`'s templates/JS (DataTables wiring) — actually paginating through
  the UI is a separate, larger follow-up; this plan only adds the API-level
  params with defaults that preserve current behavior.
- `preview_base64`/`words` column removal from the DB schema — out of scope;
  this plan does not change what's stored, only how much is returned per
  list call by default (if you choose to also add an opt-in
  `include_preview` flag, that's a reasonable stretch but not required —
  see Step 1).
- The scored transaction↔file matcher, the tax-account payment-status bug
  (plan 002), and the sync concurrency issue — unrelated findings, do not
  touch `service.py`'s `sync_*` functions in this plan.
- Applying the migration against any real/production database — only run
  `alembic upgrade head` against a local/test database in this plan's
  verification; flag the production migration as a deployment step for the
  operator, not something to execute here.

## Git workflow

- Branch: `advisor/005-read-path-performance`
- Three commits recommended, one per part, message style matching repo
  convention:
  1. `perf: add limit/offset pagination to invoice and invoice-file list endpoints`
  2. `perf: batch-load bank transactions in partner detail pages instead of N+1`
  3. `perf: index invoice_date and transaction_date columns`
- Do NOT push or open a PR unless the operator instructs it.

## Steps

### Step 1 (Part A): Add pagination params

In `invoice_service.py`, add `limit: int = 1000, offset: int = 0` params to
`list_invoices`, applied via `.offset(offset).limit(limit)` right before
`q.all()` (after `.order_by(...)`, so ordering is applied before the page
cut). Do the equivalent in `invoice_file_service.py`'s
`list_invoice_files`.

In `api/main.py`, add matching FastAPI query params to both endpoint
functions:
```python
limit: int = Query(1000, ge=1, le=5000, description="Max rows to return"),
offset: int = Query(0, ge=0, description="Rows to skip"),
```
Pass them through to the service function calls. The default of `1000`
preserves today's "return everything" behavior for current data volumes
(confirm this is larger than current row counts via
`sqlite3`/`psql` count query against a dev DB if one is available; if not
reachable, note that assumption in your report rather than guessing) while
giving callers an escape hatch as data grows.

**Verify**: `cd invoice-core && uv run pytest tests/ -v -k invoice` → existing invoice-related tests still pass with the new default-1000 behavior (no test should currently expect more than 1000 rows back, but confirm rather than assume).

### Step 2 (Part B): Fix the N+1 in `partner_service.py`

Rewrite `_partner_invoice_rows` to accept the `db: Session` and batch-load,
following the exemplar in "Current state" above exactly:

```python
def _partner_invoice_rows(db: Session, invoices: list[Invoice]) -> list[PartnerInvoiceRow]:
    rows = [
        PartnerInvoiceRow(
            id=i.id,
            invoice_number=i.invoice_number,
            invoice_date=i.invoice_date,
            amount_total=i.amount_total,
            payment_status=_enum_str(i.payment_status),
            invoice_file_id=i.invoice_file_id,
        )
        for i in invoices
    ]
    if rows:
        invoice_ids = [r.id for r in rows]
        txn_rows = (
            db.query(
                invoice_bank_transaction.c.invoice_id,
                BankTransaction.id,
                BankTransaction.transaction_id,
            )
            .join(BankTransaction, BankTransaction.id == invoice_bank_transaction.c.bank_transaction_id)
            .filter(invoice_bank_transaction.c.invoice_id.in_(invoice_ids))
            .order_by(BankTransaction.transaction_date.desc())
            .all()
        )
        first_txn: dict[int, tuple[int, str]] = {}
        for inv_id, db_id, txn_id in txn_rows:
            first_txn.setdefault(inv_id, (db_id, txn_id))  # first hit wins == latest, since ordered desc
        for row in rows:
            if row.id in first_txn:
                row.bank_txn_db_id, row.bank_txn_external_id = first_txn[row.id]
    return rows
```

You will need to import `invoice_bank_transaction` from `invoice_core.db`
in `partner_service.py` (check its current imports first — it currently
imports `BankTransaction, Customer, Invoice, Supplier, _PaymentStatus,
_enum_str` from `invoice_core.db`; add `invoice_bank_transaction` to that
line).

Update both call sites (`get_supplier` line ~257, `get_customer` around
line ~331-ish — confirm exact line via
`grep -n "_partner_invoice_rows(" invoice-core/src/invoice_core/services/partner_service.py`)
to pass `db` as the first argument: `_partner_invoice_rows(db, invoices)`.

**Verify**: `cd invoice-core && uv run pytest tests/ -v -k "supplier or customer or partner"` → all pass, and manually confirm output is unchanged by comparing a sample `get_supplier(db, <id>)` result's `invoices[].bank_txn_db_id`/`bank_txn_external_id` before and after the change (same values, same order) — write this as a test, not just a manual check (see Test plan).

### Step 3 (Part C): Add indexes and migration

In `db.py`, change:
```python
invoice_date = Column(Date, nullable=True)
```
to:
```python
invoice_date = Column(Date, nullable=True, index=True)
```
and:
```python
transaction_date = Column(DateTime, nullable=False)
```
to:
```python
transaction_date = Column(DateTime, nullable=False, index=True)
```

Generate the migration:
```bash
cd invoice-core && uv run alembic revision -m "add indexes on invoice_date and transaction_date"
```
Edit the generated file's `upgrade()`/`downgrade()` to match the style of
`j9k0l1m2n3o4_add_iban_bban_address_fields.py` (read it first), using
`op.create_index`/`op.drop_index`:

```python
def upgrade() -> None:
    op.create_index('ix_invoice_invoice_date', 'invoice', ['invoice_date'])
    op.create_index('ix_bank_transaction_transaction_date', 'bank_transaction', ['transaction_date'])


def downgrade() -> None:
    op.drop_index('ix_bank_transaction_transaction_date', table_name='bank_transaction')
    op.drop_index('ix_invoice_invoice_date', table_name='invoice')
```

Confirm the index names match what SQLAlchemy would auto-generate for
`index=True` (typically `ix_<table>_<column>`) so the model and migration
stay consistent — check by running `alembic upgrade head` against a fresh
SQLite test DB and comparing to what `Base.metadata.create_all` produces
for a from-scratch schema (the two should not diverge, since production
uses migrations but tests use `create_all`).

**Verify**: `cd invoice-core && uv run alembic upgrade head` against a local/test DB → exit 0. `cd invoice-core && uv run pytest tests/ -v` → all still pass (tests use `create_all`, which will pick up `index=True` automatically — this confirms the model change didn't break anything, independent of the migration).

## Test plan

- Part A: add or extend a test in `invoice-core/tests/` asserting
  `invoice_service.list_invoices(db, limit=2, offset=0)` returns exactly 2
  rows when more than 2 matching invoices exist, and that
  `offset=2` returns the next page (different rows, no overlap). Model
  after the existing invoice-listing tests in `invoice-core/tests/`
  (check `test_models.py` or wherever `list_invoices` is currently tested).
- Part B: add a test asserting `get_supplier`'s returned
  `invoices[].bank_txn_db_id` / `bank_txn_external_id` match what the old
  N+1 code would have produced, for a supplier with 2+ invoices each having
  a different number of linked transactions (0, 1, and 2+) — this is the
  regression test that protects the batch-rewrite from silently changing
  output.
- Part C: no new test strictly required beyond confirming the full suite
  still passes with `index=True` added (SQLAlchemy's `create_all` in
  `conftest.py` picks this up automatically) — the migration itself is
  verified via `alembic upgrade head` succeeding, not a pytest test.
- Verification: `cd invoice-core && uv run pytest tests/ -v` → all pass, including new tests for Parts A and B.

## Done criteria

- [ ] `cd invoice-core && uv run pytest tests/ -v` exits 0, all pass including new tests
- [ ] `list_invoices` and `list_invoice_files` (both API and service layer) accept `limit`/`offset` with defaults that don't change current output for today's data volumes
- [ ] `partner_service.py`'s `_partner_invoice_rows` issues one batched query instead of one query per invoice (confirm via `grep -c "bank_transactions\[0\]" invoice-core/src/invoice_core/services/partner_service.py` → `0`)
- [ ] `Invoice.invoice_date` and `BankTransaction.transaction_date` both have `index=True` in `db.py`
- [ ] A new alembic migration exists adding both indexes, and `alembic upgrade head` succeeds against a local/test DB
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated, noting that wiring `vision` to actually paginate is an explicit follow-up, not done here

## STOP conditions

- If any existing test currently asserts more than 1000 rows are returned
  from `list_invoices`/`list_invoice_files` (i.e. the default limit would
  break a real test expectation), STOP and report — do not silently raise
  the default limit to make the test pass without understanding why that
  test expects unbounded results.
- If `_partner_invoice_rows`'s batch rewrite produces different
  `bank_txn_db_id`/`bank_txn_external_id` values than the original N+1 code
  for any test case (i.e. "first" transaction per invoice is ambiguous or
  ordered differently than expected), STOP and report the discrepancy
  rather than picking whichever tiebreak makes tests pass.
- If `alembic revision`/`upgrade head` fails or the generated migration's
  autogenerated index name doesn't match what `index=True` produces via
  `create_all`, STOP and report — don't hand-edit index names to force a
  match without understanding the mismatch.

## Maintenance notes

- The `limit`/`offset` params added here are a stopgap, not a full paging
  UI — a future plan should update `vision`'s templates to actually walk
  through pages via these params (currently DataTables assumes the whole
  result set is already in the DOM). Whoever picks that up should read this
  plan's Part A "Current state" note about that assumption first.
- If invoice/transaction volumes are expected to grow well past a few
  thousand rows per supplier/customer, the batch query in Part B may itself
  eventually want its own limit — not needed at today's scale, but worth
  revisiting if a single partner accumulates thousands of invoices.
- Applying the new migration against the production database is a
  deployment step, not part of this plan's verification — the operator
  should run `alembic upgrade head` against production separately, ideally
  during low-traffic hours since index creation briefly locks writes in
  PostgreSQL.
