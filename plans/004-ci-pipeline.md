# Plan 004: Add CI to run every sub-project's test suite on push/PR

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 56f4d65..HEAD -- '*/pyproject.toml' '*/tests'`
> If any sub-project gained/lost a test directory or changed its
> `requires-python` since this plan was written, re-check the project table
> below against the live repo before proceeding.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `56f4d65`, 2026-07-16

## Why this matters

This workspace has 9+ independent Python microservices, most with real
`pytest` suites (see table below), but there is **no CI configuration
anywhere in the repo** — no `.github/workflows`, no `.circleci`, no
`Jenkinsfile`, nothing (confirmed absent via filesystem search). Every test
suite only runs if a developer remembers to `cd <project> && uv run
pytest` manually. A single GitHub Actions workflow that matrixes over the
sub-projects with tests would catch regressions automatically on every push
and PR, at low effort since each project is already self-contained (its own
`.venv`/`pyproject.toml`/`uv.lock`).

## Current state

Root of the repo has no `.github/` directory at all — confirmed via
`find . -maxdepth 2 -iname ".github"` (empty output) and
`find . -maxdepth 3 -iname "*.yml" -path "*workflows*"` (empty output).

Test presence per sub-project (confirmed via `find <dir>/tests -name
"test_*.py" | wc -l`):

| Sub-project | Test files | `requires-python` | Notes |
|---|---|---|---|
| `nav-invoice` | 2 | >=3.11 | plain `uv sync` |
| `attachment-downloader` | 2 | >=3.9 | needs `uv sync --extra gmail` — tests import `attachment_downloader.providers.gmail.client`, which needs the `gmail` extra's deps (`google-api-python-client` etc.) even though no real Gmail API call happens (mocked via `unittest.mock.patch`) |
| `invoice-file-filter` | 3 | >=3.10 | plain `uv sync`; OCR system deps (`poppler`, `tesseract`) are NOT required for the test suite unless a test exercises OCR directly — check `tests/` for any OCR-dependent test before assuming CI needs system packages; if one exists, add `apt-get install -y poppler-utils tesseract-ocr` to that job only |
| `invoice-core` | 5 | >=3.10 | plain `uv sync`; tests use in-memory SQLite (`tests/conftest.py`), no PostgreSQL needed for CI |
| `wise` | 2 | >=3.10 | plain `uv sync` |
| `bank` | 0 → will have tests after plan 003 lands | >=3.11 | include in matrix regardless — an empty `tests/` dir makes `pytest` exit 0 (no tests collected) which is a valid "nothing to run yet" state, not a failure |
| `vision` | 1 | >=3.11 | plain `uv sync` |
| `auth` | 3 | >=3.11 | plain `uv sync` |
| `uploader` | 0 | >=3.11 | include in matrix (same "0 tests is fine" reasoning as bank) |

`banking/` and `vault-agent/` have no `tests/` directory structure
matching the pattern above (`vault-agent` has ad-hoc `test_agent.py`/
`test_web.py` at its root, not in a `tests/` subdir) — see "Out of scope."

Every sub-project already has a committed `uv.lock` (confirmed via
`git ls-files | grep uv.lock` — all 9 above plus `banking`/`vault-agent`
have one), so `uv sync` in CI will reproduce exact dependency versions
without needing a fresh resolve.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Local dry-run of one project's CI-equivalent commands | `cd invoice-core && uv sync && uv run pytest tests/ -v` | all pass, matches what CI will do |
| Validate workflow YAML syntax (no GitHub Actions locally, so just YAML-parse it) | `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml'))"` | no exception |

## Scope

**In scope**:
- `.github/workflows/test.yml` (create)

**Out of scope** (do NOT touch, do NOT add to the CI matrix):
- `banking/` and `vault-agent/` — neither has a `tests/` directory in the
  standard shape this plan's matrix expects (`vault-agent` has test files
  at its root, not under `tests/`); adding them requires a different job
  shape and is not part of this plan. Note them as a follow-up in your
  final report, do not improvise a special-case job for them.
- Do not add a lint/format job (ruff is not configured anywhere in the repo
  — that's a separate, already-identified finding; adding lint CI before
  ruff exists would just fail every run).
- Do not add deployment, Docker build, or release steps — test-running only.
- Do not modify any project's `pyproject.toml`, source, or existing tests.

## Git workflow

- Branch: `advisor/004-ci-pipeline`
- Single commit: `ci: add GitHub Actions workflow to run every sub-project's test suite`
- Do NOT push or open a PR unless the operator instructs it. (Note: since
  this changes `.github/workflows/`, actually exercising it end-to-end
  requires a push to GitHub — you cannot fully verify a real Actions run
  locally. Verify what you can locally, per the Steps below, and say so
  explicitly in your final report.)

## Steps

### Step 1: Check whether `invoice-file-filter`'s tests need OCR system packages

```bash
grep -rln "pytesseract\|ocr\|OCR" invoice-file-filter/tests/*.py
```

If this returns matches, read those test(s) to see if they actually invoke
OCR (vs. just importing a module that has an OCR code path but mocks it
out). If real OCR execution is needed, the `invoice-file-filter` job in
Step 2 needs an extra `apt-get install -y poppler-utils tesseract-ocr
tesseract-ocr-hun` step before `uv sync`. If no test exercises OCR directly,
skip this — plain `uv sync` is enough.

**Verify**: document your finding (which case applies) before writing Step 2's workflow file, since it changes that job's content.

### Step 2: Write `.github/workflows/test.yml`

```yaml
name: Tests

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        include:
          - project: nav-invoice
            python-version: "3.11"
          - project: attachment-downloader
            python-version: "3.9"
            extra: gmail
          - project: invoice-file-filter
            python-version: "3.10"
          - project: invoice-core
            python-version: "3.10"
          - project: wise
            python-version: "3.10"
          - project: bank
            python-version: "3.11"
          - project: vision
            python-version: "3.11"
          - project: auth
            python-version: "3.11"
          - project: uploader
            python-version: "3.11"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        working-directory: ${{ matrix.project }}
        run: |
          if [ -n "${{ matrix.extra }}" ]; then
            uv sync --extra ${{ matrix.extra }}
          else
            uv sync
          fi

      - name: Run tests
        working-directory: ${{ matrix.project }}
        run: uv run pytest tests/ -v
```

If Step 1 found `invoice-file-filter` needs OCR system packages, add a
conditional step before "Install dependencies" for that matrix entry only,
e.g. an `if: matrix.project == 'invoice-file-filter'` step running
`sudo apt-get update && sudo apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-hun`.

**Verify**: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml'))"` → no exception (valid YAML).

### Step 3: Locally dry-run the exact commands for at least 3 representative projects

Since GitHub Actions can't be run locally, manually execute the same
`working-directory` + `run` commands the workflow specifies, for at least
`invoice-core` (has DB-adjacent tests), `attachment-downloader` (has the
`--extra gmail` special case), and one plain project (e.g. `auth`):

```bash
cd invoice-core && uv sync && uv run pytest tests/ -v
cd ../attachment-downloader && uv sync --extra gmail && uv run pytest tests/ -v
cd ../auth && uv sync && uv run pytest tests/ -v
```

**Verify**: all three exit 0 with all tests passing — this is your evidence the workflow's commands are correct, even though the workflow itself can't be executed outside GitHub.

### Step 4: Commit

```bash
git add .github/workflows/test.yml
git commit -m "ci: add GitHub Actions workflow to run every sub-project's test suite"
```

**Verify**: `git show --stat HEAD` shows exactly one new file.

## Test plan

There is no "test for a CI config" beyond what Step 3 already covers
(locally reproducing the exact commands the workflow runs). The real
verification only happens once this is pushed and a workflow run completes
on GitHub — state clearly in your final report that this step could not be
verified end-to-end locally, and that the operator should check the
Actions tab after merging.

## Done criteria

- [ ] `.github/workflows/test.yml` exists and is valid YAML
- [ ] The matrix includes exactly: nav-invoice, attachment-downloader (with `extra: gmail`), invoice-file-filter, invoice-core, wise, bank, vision, auth, uploader — 9 entries
- [ ] Step 3's local dry-runs (at least 3 projects) all passed
- [ ] No files outside `.github/workflows/test.yml` created or modified (`git status`)
- [ ] `plans/README.md` status row updated, with an explicit note that full end-to-end verification requires a push to GitHub

## STOP conditions

- If any sub-project's local dry-run in Step 3 fails for a reason unrelated
  to CI setup (e.g. a genuinely broken test), STOP and report the failure —
  do not silently skip that project from the matrix or mark its job
  `continue-on-error`.
- If `invoice-file-filter`'s tests turn out to need OCR system packages
  (Step 1) and you're unsure whether the `apt-get` package names are
  correct for the Ubuntu runner version, STOP and report your uncertainty
  rather than guessing package names that might silently no-op.

## Maintenance notes

- `banking/` and `vault-agent/` are deliberately excluded (see Scope) —
  if either gains a standard `tests/` directory in the future, add it to
  the matrix following the same pattern.
- Once ruff is added to the repo (a separate identified gap), a follow-up
  PR should add a lint job to this same workflow file.
- The matrix's Python versions are pinned per-project's `requires-python`
  floor; if any project's `requires-python` changes, update the matching
  matrix entry.
