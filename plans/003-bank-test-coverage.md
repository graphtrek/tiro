# Plan 003: Add tests for bank CSV parsers and fix the self-referential tax-guard test

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 56f4d65..HEAD -- bank/src/bank/parsers bank/tests invoice-core/tests/test_matching.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts below against the live code before proceeding; on
> a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S–M
- **Risk**: LOW (adding tests, one test refactor)
- **Depends on**: none (independent of plan 002, though both touch `invoice-core/tests/test_matching.py` — coordinate if executing both in the same session to avoid a merge conflict on that file)
- **Category**: tests
- **Planned at**: commit `56f4d65`, 2026-07-16

## Why this matters

Two distinct but related gaps:

1. `bank/src/bank/parsers/erste.py` and `bank/src/bank/parsers/wise.py` are
   the literal entry point for all financial transaction data into this
   pipeline (`invoice-core`'s `sync_bank` trusts whatever the `bank` service
   returns). `bank/tests/` exists as a directory but contains **zero
   files** — not even `__init__.py`. A regression in amount parsing,
   date-format handling, or the deterministic-ID fallback (used when a CSV
   row has no bank-provided transaction ID) would silently corrupt or
   duplicate financial records with nothing to catch it.
2. `invoice-core/tests/test_matching.py:457-492`
   (`test_locked_txn_not_cleared_by_tax_guard`) has a comment admitting it
   can't call the real `sync_bank` function ("sync_bank calls BankClient
   which we can't mock here") and instead copy-pastes the exact filter
   expression from `service.py`'s tax-account guard and asserts against its
   own copy. If the real guard in `service.py` regresses, this test keeps
   passing because it never actually exercises that code — false confidence
   on a money-safety guard.

## Current state

### Part A: `bank` parser tests

`bank/tests/` — confirmed empty (`ls -la bank/tests/` shows only `.` and
`..`, no `__init__.py`).

`bank/src/bank/parsers/erste.py` — key functions to test (full file is 158
lines, read it before writing tests):
- `_parse_amount(raw: str) -> Decimal` (line 43) — strips `\xa0` (non-breaking
  space) thousands separators, then `Decimal(...)`; raises `ValueError` on
  bad input.
- `_parse_balance(raw: str) -> Decimal | None` (line 52) — parses
  `"3\xa0343\xa0587 HUF"` shaped strings, returns `None` on empty/unparseable
  input.
- `_parse_date` / `_parse_datetime` (lines 64, 73) — `YYYY.MM.DD` and
  `YYYY.MM.DD HH:MM:SS` formats, return `None` on bad input rather than
  raising.
- `_make_id(row, occurrence)` (line 88) — SHA1-based deterministic ID for
  rows missing `Tranzakcióazonosító` (e.g. card transactions); `occurrence`
  is the Nth time a `(date, amount, description)` key repeats within the
  file, not the row's absolute position (see the function's own docstring
  for why — it's designed to stay stable across overlapping-date exports).
- `parse_erste_csv(path: Path) -> list[BankTransaction]` (line 100) — the
  public entry point; opens the file as `encoding="utf-16"`, uses
  `csv.DictReader`, skips rows with unparseable date/amount (logs a warning,
  continues rather than raising).

`bank/src/bank/parsers/wise.py` — key functions (155 lines):
- `_parse_date` / `_parse_datetime` (lines 50, 61) — tries 3 formats in
  order: `"%d-%m-%Y %H:%M:%S.%f"`, `"%d-%m-%Y %H:%M:%S"`, `"%d-%m-%Y"`.
- `_parse_amount` (line 72) — plain `Decimal(...)`, returns `None` on bad
  input.
- `parse_wise_csv(path: Path) -> list[BankTransaction]` (line 85) — opens as
  `encoding="utf-8-sig"`; **skips rows entirely if `TransferWise ID` is
  blank** (line 91-93) — unlike Erste, Wise rows with no ID are dropped, not
  given a synthetic ID. This asymmetry is worth a test that documents it's
  intentional, not a gap in your new tests.

`bank/src/bank/models.py` — `BankTransaction` is a Pydantic `BaseModel` (not
a DB model) with fields: `bank`, `transaction_id`, `date`, `datetime`,
`amount` (`Decimal`), `currency`, `direction` (`Literal["CREDIT","DEBIT"]`),
`description`, `payment_reference`, `counterparty_name`,
`counterparty_account`, `counterparty_iban`, `transaction_type`, `category`,
`balance`, `fees`, plus Erste-only (`counterparty_address`,
`sender_address`, `counterparty_bank_code`) and Wise-only (`exchange_rate`,
`exchange_to_currency`, `card_last_four`, `note`) optional fields.

`bank/pyproject.toml` already lists `pytest>=8.0` and `httpx>=0.27` under
`[dependency-groups] dev` — no dependency changes needed.

### Part B: self-referential test

`invoice-core/tests/test_matching.py:457-492` (full current test):

```python
def test_locked_txn_not_cleared_by_tax_guard(mdb):
    """sync_bank's tax-account clearing must skip transactions with invoice_file_locked=True."""
    from invoice_core.config import Settings
    from invoice_core.service import sync_bank

    tax_account = "10032000-00290080-00000000"
    settings = Settings(
        db_url="sqlite:///:memory:",
        tax_accounts={tax_account: "NAV ÁFA"},
    )

    f = InvoiceFile(filename="locked.pdf", words="content")
    mdb.add(f)
    mdb.flush()

    txn = _txn(
        transaction_id="TAX-LOCKED-1",
        amount=5000,
        counterparty_account=tax_account,
        invoice_file_id=f.id,
        invoice_file_locked=True,
    )
    mdb.add(txn)
    mdb.flush()

    # sync_bank calls BankClient which we can't mock here, so test the guard logic directly
    # by replicating the clearing logic and verifying the lock is respected
    tax_keys = list(settings.tax_accounts.keys())
    tax_txns = mdb.query(BankTransaction).filter(
        BankTransaction.counterparty_account.in_(tax_keys)
    ).all()
    wrongly_linked = [
        t for t in tax_txns
        if (t.invoices or t.invoice_file_id) and not t.invoice_file_locked
    ]
    assert len(wrongly_linked) == 0  # locked txn must be excluded from clearing
```

`sync_bank`'s signature and how it constructs `BankClient` — read
`invoice-core/src/invoice_core/service.py` around the `sync_bank` function
definition and its `BankClient(settings).get_transactions()` call (~line
559) before writing the fix, so you know exactly what to monkeypatch.
Search `invoice-core/tests/` for any existing test that already
monkeypatches `BankClient` (e.g. `monkeypatch.setattr(BankClient,
"get_transactions", ...)`) — the audit that found this issue noted a
sibling test in this same file uses that pattern; find and copy it rather
than inventing a new mocking approach.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Sync bank deps | `cd bank && uv sync` | exit 0 |
| Run bank tests | `cd bank && uv run pytest tests/ -v` | all pass, new tests included |
| Sync invoice-core deps | `cd invoice-core && uv sync` | exit 0 |
| Run invoice-core matching tests | `cd invoice-core && uv run pytest tests/test_matching.py -v` | all pass |

## Scope

**In scope**:
- `bank/tests/__init__.py` (create, empty)
- `bank/tests/test_parsers.py` (create)
- `bank/tests/fixtures/` (create — sample CSV fixture files)
- `invoice-core/tests/test_matching.py` — rewrite
  `test_locked_txn_not_cleared_by_tax_guard` only

**Out of scope**:
- Do not modify `bank/src/bank/parsers/erste.py` or `wise.py` themselves —
  this plan adds tests for existing behavior, it does not change parser
  logic. If a test reveals what looks like a real bug, STOP and report
  rather than fixing it silently (see STOP conditions).
- Do not touch any other test file in `invoice-core/tests/`.
- Do not add tests for `bank/src/bank/service.py`, `api/main.py`, or
  `cli/main.py` — this plan is scoped to the parser functions only.

## Git workflow

- Branch: `advisor/003-bank-test-coverage`
- Two commits recommended (one per part), message style matching repo
  convention:
  1. `test: add coverage for Erste/Wise bank statement CSV parsers`
  2. `test: exercise sync_bank directly in tax-guard lock test instead of duplicating its logic`
- Do NOT push or open a PR unless the operator instructs it.

## Steps

### Step 1: Create fixture CSV files

Create `bank/tests/fixtures/erste_sample.csv` — a small UTF-16-encoded CSV
with the Erste column headers from `erste.py` (`_COL_DATE` through
`_COL_SENDER_ADDRESS`), containing at minimum:
- One normal row with a `Tranzakcióazonosító` present, a positive amount, a
  balance like `"3\xa0343\xa0587 HUF"`.
- One row with a negative amount (DEBIT direction).
- One row with **no** `Tranzakcióazonosító` (to exercise `_make_id`), and a
  second row identical in date/amount/description to it (to exercise the
  `occurrence` counter incrementing — this is the trickiest part of the
  dedup logic and the one most worth locking down with a test).
- One row with an empty/malformed amount (to exercise the skip-with-warning
  path).

Because the file must be UTF-16 encoded, write it with a small Python
snippet rather than a text editor, e.g.:
```python
import csv
rows = [...]
with open("bank/tests/fixtures/erste_sample.csv", "w", encoding="utf-16", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=[...])
    writer.writeheader()
    writer.writerows(rows)
```

Create `bank/tests/fixtures/wise_sample.csv` (UTF-8) similarly, with:
- One normal row with a `TransferWise ID` present.
- One row with **no** `TransferWise ID` (must be dropped entirely — not
  given a synthetic ID, unlike Erste).
- One row with a malformed `Amount`.

**Verify**: `python3 -c "import csv; print(len(list(csv.DictReader(open('bank/tests/fixtures/erste_sample.csv', encoding='utf-16')))))"` → prints the row count you created (sanity check the fixture parses at all before writing assertions against it).

### Step 2: Write `bank/tests/test_parsers.py`

Cover, at minimum:
- `parse_erste_csv` on the fixture: correct row count returned (malformed
  rows skipped), correct `Decimal` amounts, correct `direction` for the
  negative-amount row, correct synthetic IDs for the no-ID rows (assert the
  two duplicate-key rows get *different* IDs — this is the specific
  behavior `_make_id`'s `occurrence` parameter exists for).
- `parse_wise_csv` on the fixture: correct row count (the no-ID row is
  absent from the result, not present-with-a-fallback-id), correct
  `Decimal` amounts.
- Unit tests for `_parse_amount`, `_parse_balance` (both files) directly:
  valid input, empty string, malformed string — assert the documented
  behavior (raises `ValueError` for Erste's `_parse_amount`, returns `None`
  for Wise's).

**Verify**: `cd bank && uv run pytest tests/test_parsers.py -v` → all new tests pass.

### Step 3: Fix the self-referential test in `invoice-core`

First, find the existing monkeypatch pattern:
```bash
grep -n "monkeypatch.setattr(BankClient" invoice-core/tests/*.py
```

Rewrite `test_locked_txn_not_cleared_by_tax_guard` to call `sync_bank`
directly with `BankClient.get_transactions` monkeypatched to return `[]`
(no new transactions — the test only cares about the tax-account cleanup
phase's handling of the *existing* locked transaction), then assert the
locked transaction is unchanged after the call:

```python
def test_locked_txn_not_cleared_by_tax_guard(mdb, monkeypatch):
    """sync_bank's tax-account clearing must skip transactions with invoice_file_locked=True."""
    from invoice_core.config import Settings
    from invoice_core.service import sync_bank
    from invoice_core.bank_client import BankClient

    tax_account = "10032000-00290080-00000000"
    settings = Settings(
        db_url="sqlite:///:memory:",
        tax_accounts={tax_account: "NAV ÁFA"},
    )

    f = InvoiceFile(filename="locked.pdf", words="content")
    mdb.add(f)
    mdb.flush()

    txn = _txn(
        transaction_id="TAX-LOCKED-1",
        amount=5000,
        counterparty_account=tax_account,
        invoice_file_id=f.id,
        invoice_file_locked=True,
    )
    mdb.add(txn)
    mdb.flush()

    monkeypatch.setattr(BankClient, "get_transactions", lambda self: [])
    sync_bank(mdb, settings)

    mdb.refresh(txn)
    assert txn.invoice_file_id == f.id  # still linked — the lock protected it
    assert txn.invoice_file_locked is True
```

Adjust the exact import path for `BankClient` and the `sync_bank` call
signature to match what's actually in `service.py` — the sketch above is
illustrative; confirm against the real signatures before finalizing (part
of your drift check).

**Verify**: `cd invoice-core && uv run pytest tests/test_matching.py -v -k test_locked_txn_not_cleared_by_tax_guard` → 1 passed, and confirm via `grep -n "replicating the clearing logic" invoice-core/tests/test_matching.py` that the old comment/self-referential code is gone.

### Step 4: Run both full suites

**Verify**: `cd bank && uv run pytest tests/ -v` → all pass. `cd invoice-core && uv run pytest tests/ -v` → all pass, no regressions.

## Test plan

Already detailed in Steps 2–3 above. Summary:
- `bank/tests/test_parsers.py`: new file, ~8-10 test cases across both
  parsers covering normal rows, malformed rows, and the ID-fallback/ID-drop
  asymmetry between Erste and Wise.
- `invoice-core/tests/test_matching.py`: one existing test rewritten to call
  production code instead of duplicating it.
- Verification: `cd bank && uv run pytest tests/ -v` and
  `cd invoice-core && uv run pytest tests/ -v`, both exit 0.

## Done criteria

- [ ] `cd bank && uv run pytest tests/ -v` exits 0, includes new parser tests
- [ ] `cd invoice-core && uv run pytest tests/ -v` exits 0
- [ ] `grep -rn "replicating the clearing logic" invoice-core/tests/` returns no matches
- [ ] `bank/tests/test_parsers.py` and `bank/tests/fixtures/*.csv` exist and are used by the tests (not dead fixtures)
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

- If writing a test against `parse_erste_csv` or `parse_wise_csv` reveals
  output that looks wrong (e.g. an amount that doesn't match what the CSV
  says, a date silently misparsed), STOP and report the specific input/
  output — do not "fix" the parser as a side effect of this test-only plan.
- If `BankClient.get_transactions` can't be cleanly monkeypatched (e.g. its
  constructor requires live network config with no seam), it's acceptable
  to keep testing the guard logic in isolation, but note explicitly in the
  test's docstring why the direct-call approach wasn't possible — don't
  silently leave the old self-referential comment in place.
- If the existing test suite already has UTF-16 CSV fixtures elsewhere in
  the repo you could reuse instead of creating new ones, prefer reusing
  them — check `nav-invoice/tests/` and `invoice-file-filter/tests/` for
  any existing CSV/PDF fixture patterns before writing new fixture-generation
  code from scratch.

## Maintenance notes

- The Erste/Wise ID-fallback asymmetry (Erste synthesizes an ID via SHA1;
  Wise drops rows with no ID entirely) is intentional per the current code,
  but is exactly the kind of thing that's easy to "fix into consistency" by
  accident in a future refactor — the new tests in this plan exist partly to
  guard against that.
- If `bank/service.py` or `api/main.py` are touched in a future change, they
  still have zero test coverage after this plan — this plan intentionally
  scoped down to parsers only (the highest-risk, pure-function part); a
  follow-up plan could extend coverage to the service/API layer.
