# Plan 002: Recompute invoice payment status when a tax-account link is cleared

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 56f4d65..HEAD -- invoice-core/src/invoice_core/service.py invoice-core/tests`
> If `service.py` changed since this plan was written, compare the "Current
> state" excerpts below against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `56f4d65`, 2026-07-16

## Why this matters

`invoice-core` is the system of record for whether an invoice is PAID,
PARTIAL, or UNPAID, derived from which bank transactions are linked to it
(`_recompute_payment_status` in `service.py`). `sync_bank`'s tax-account
cleanup phase (the code that detects a bank transaction wrongly linked to an
invoice because it turned out to be a payment to a tax authority account,
e.g. NAV ÁFA) clears that link — but never re-runs
`_recompute_payment_status` on the invoice that just lost its transaction.
Worse, `_recompute_payment_status` itself returns immediately when an
invoice has zero linked transactions, so even if something else calls it
later, an invoice that dropped to zero linked transactions never gets
corrected back to UNPAID. Net effect: an invoice can keep showing as PAID
indefinitely with no bank transaction actually backing that status — a
silently wrong "money is settled" signal in a system whose entire purpose is
financial reconciliation.

## Current state

`invoice-core/src/invoice_core/service.py:72-98` —
`_recompute_payment_status`:

```python
def _recompute_payment_status(db: Session, invoice: Invoice) -> None:
    """Set PAID/PARTIAL/UNPAID from the sum of linked transaction amounts.

    Skipped when payment_status_locked is set (manually overridden status).
    Compares against invoice.amount_total using only transactions whose currency
    matches the invoice currency (if set). Falls back to PAID when amount_total
    is unknown.
    """
    if getattr(invoice, "payment_status_locked", False):
        return
    linked = invoice.bank_transactions
    if not linked:
        return
    total = invoice.amount_total or 0.0
    currency = invoice.currency
    paid_sum = sum(abs(t.amount) for t in linked if not currency or t.currency == currency)
    if total <= 0:
        new_status = _PaymentStatus.PAID
    elif paid_sum >= total:
        new_status = _PaymentStatus.PAID
    elif paid_sum > 0:
        new_status = _PaymentStatus.PARTIAL
    else:
        new_status = _PaymentStatus.UNPAID
    if invoice.payment_status != new_status:
        invoice.payment_status = new_status
        invoice.updated_at = datetime.utcnow()
```

Note line 83: `if not linked: return` — this is the second half of the bug.
An invoice with zero linked transactions is left exactly as it was, never
forced back to UNPAID.

`invoice-core/src/invoice_core/service.py:541-557` — the tax-account
cleanup phase inside `sync_bank` (this is the call site missing the fix):

```python
    # Clear any previously created links on tax-account transactions.
    tax_keys = list(settings.tax_accounts.keys())
    if tax_keys:
        tax_txns = db.query(BankTransaction).filter(
            BankTransaction.counterparty_account.in_(tax_keys)
        ).all()
        wrongly_linked = [
            tax_txn for tax_txn in tax_txns
            if (tax_txn.invoices or tax_txn.invoice_file_id) and not tax_txn.invoice_file_locked
        ]
        for btxn in wrongly_linked:
            btxn.invoices.clear()
            btxn.invoice_file_id = None
            btxn.supplier_id = None
            btxn.customer_id = None
        if wrongly_linked:
            logger.info("Cleared links from %d tax-account transaction(s)", len(wrongly_linked))
```

`btxn.invoices` is the many-to-many collection (via `invoice_bank_transaction`,
see `db.py:181-186`) — `btxn.invoices.clear()` on line 552 removes `btxn`
from every invoice's `bank_transactions` collection it was in, but no
invoice is touched or recomputed afterward.

For contrast, every other place in this file that changes an
invoice↔transaction link already calls `_recompute_payment_status`
immediately afterward — e.g. `service.py:639` and `service.py:954` (grep
`_recompute_payment_status(` to see all current call sites before editing,
so your new call site follows the same pattern).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install/sync | `cd invoice-core && uv sync` | exit 0 |
| Run full test suite | `cd invoice-core && uv run pytest tests/ -v` | all pass |
| Run just the matching tests | `cd invoice-core && uv run pytest tests/test_matching.py -v` | all pass, including new test |

## Scope

**In scope**:
- `invoice-core/src/invoice_core/service.py` — the `sync_bank` tax-account
  cleanup block (~line 541-557) and `_recompute_payment_status` (~line
  72-98).
- `invoice-core/tests/test_matching.py` — add a new regression test.

**Out of scope** (do NOT touch, even though related):
- The scored transaction↔file matcher (`_file_score`, `_names_overlap`,
  `_MATCH_THRESHOLD`) — a separate, higher-effort finding about match
  confidence, not part of this bug.
- The concurrency/locking behavior of `sync_all` — separate finding.
- `_recompute_payment_status`'s currency-matching or `payment_status_locked`
  semantics beyond the empty-`linked` branch — do not change any other
  branch of this function's logic.

## Git workflow

- Branch: `advisor/002-fix-payment-status-recompute`
- Single commit, message style matching repo convention, e.g.:
  `fix: recompute invoice payment status after clearing tax-account transaction links`
- Do NOT push or open a PR unless the operator instructs it.

## Steps

### Step 1: Fix the empty-`linked` branch in `_recompute_payment_status`

Change the early return so that an invoice with zero linked transactions is
explicitly set to UNPAID (unless locked), instead of being left untouched:

```python
def _recompute_payment_status(db: Session, invoice: Invoice) -> None:
    if getattr(invoice, "payment_status_locked", False):
        return
    linked = invoice.bank_transactions
    if not linked:
        if invoice.payment_status != _PaymentStatus.UNPAID:
            invoice.payment_status = _PaymentStatus.UNPAID
            invoice.updated_at = datetime.utcnow()
        return
    total = invoice.amount_total or 0.0
    ...
```

(Keep the rest of the function body unchanged — only the `if not linked:`
branch changes.)

**Verify**: `grep -A4 "if not linked:" invoice-core/src/invoice_core/service.py` shows the new UNPAID-setting branch.

### Step 2: Recompute affected invoices in the tax-account cleanup loop

Collect the distinct invoices touched by the `wrongly_linked` loop *before*
clearing (since `.clear()` empties the collection you'd otherwise need to
read from), then call `_recompute_payment_status` on each afterward:

```python
    if tax_keys:
        tax_txns = db.query(BankTransaction).filter(
            BankTransaction.counterparty_account.in_(tax_keys)
        ).all()
        wrongly_linked = [
            tax_txn for tax_txn in tax_txns
            if (tax_txn.invoices or tax_txn.invoice_file_id) and not tax_txn.invoice_file_locked
        ]
        affected_invoices = {inv for tax_txn in wrongly_linked for inv in tax_txn.invoices}
        for btxn in wrongly_linked:
            btxn.invoices.clear()
            btxn.invoice_file_id = None
            btxn.supplier_id = None
            btxn.customer_id = None
        for inv in affected_invoices:
            _recompute_payment_status(db, inv)
        if wrongly_linked:
            logger.info("Cleared links from %d tax-account transaction(s)", len(wrongly_linked))
```

**Verify**: `grep -n "affected_invoices" invoice-core/src/invoice_core/service.py` shows the new set-comprehension and the loop calling `_recompute_payment_status`.

### Step 3: Add a regression test

In `invoice-core/tests/test_matching.py`, add a test that:
1. Creates an invoice with `amount_total=5000`, `payment_status=PAID`.
2. Links a bank transaction to it (via the same helper pattern the existing
   tests in this file use, e.g. `_txn(...)` — read the top of the file for
   the exact fixture helpers before writing this).
3. Marks that transaction's `counterparty_account` as a tax account
   (matching a `tax_accounts` key in `Settings`) and re-runs the relevant
   portion of `sync_bank`'s cleanup logic (or calls `sync_bank` directly if
   `BankClient` can be monkeypatched to return no new transactions — prefer
   this over replicating logic, per the note in Step 4 below).
4. Asserts the invoice's `payment_status` is now `UNPAID` and
   `bank_transactions` is empty.

Name it `test_tax_account_clearing_recomputes_payment_status`.

**Verify**: `cd invoice-core && uv run pytest tests/test_matching.py -v -k test_tax_account_clearing_recomputes_payment_status` → 1 passed.

### Step 4: Run the full suite

**Verify**: `cd invoice-core && uv run pytest tests/ -v` → all pass, no regressions in existing tests (particularly `test_locked_txn_not_cleared_by_tax_guard` at `test_matching.py:457`, which exercises the same code path and must still pass).

## Test plan

- New test: `test_tax_account_clearing_recomputes_payment_status` in
  `invoice-core/tests/test_matching.py`, modeled on the existing
  `test_locked_txn_not_cleared_by_tax_guard` (same file, ~line 457) for
  fixture setup style — but unlike that test, prefer actually calling
  `sync_bank` with a monkeypatched `BankClient.get_transactions` returning
  `[]` (see if any other test in the file already does this monkeypatch
  pattern; if so, copy it) rather than replicating the clearing logic
  inline — the whole point of this plan is to test the real code path, not
  a copy of it.
- Verification: `cd invoice-core && uv run pytest tests/ -v` → all pass.

## Done criteria

- [ ] `cd invoice-core && uv run pytest tests/ -v` exits 0, all pass including the new test
- [ ] `grep -n "affected_invoices" invoice-core/src/invoice_core/service.py` shows the fix in `sync_bank`
- [ ] An invoice that loses its only linked transaction via the tax-account cleanup path shows `payment_status == UNPAID` (verified by the new test)
- [ ] No files outside `invoice-core/src/invoice_core/service.py` and `invoice-core/tests/test_matching.py` modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

- If `_recompute_payment_status` or the tax-account cleanup block has
  materially different logic than the excerpts above (drift check), stop
  and report rather than patching around a mismatch.
- If the existing test suite has a test that asserts an invoice keeps its
  PAID status after all transactions are cleared (i.e. the current buggy
  behavior is deliberately tested elsewhere), STOP — that would mean this
  "bug" is actually relied upon somewhere, and the fix needs product
  sign-off, not just a code change.
- If `BankClient.get_transactions` cannot be monkeypatched cleanly (e.g. it's
  constructed in a way sibling tests don't already handle), it's acceptable
  to fall back to calling the cleanup block's logic directly in the test —
  but note this fallback explicitly in your test's docstring so a future
  reader knows it's a second-choice approach, not silently repeat the
  self-referential pattern this plan exists to avoid perpetuating.

## Maintenance notes

- This same "clear a link without recomputing" shape is worth double-checking
  anywhere else invoice↔transaction links are removed in `service.py` — this
  plan only fixes the tax-account cleanup call site because that's the one
  found during the audit; if a reviewer spots another link-removal site
  missing a recompute call, it's the same class of bug.
- The scored transaction↔file matcher (mentioned in "Out of scope" above) is
  a separate, related finding — a future plan may want to add a persisted
  match-confidence field; this plan does not touch that.
