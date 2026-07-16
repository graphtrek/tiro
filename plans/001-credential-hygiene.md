# Plan 001: Remove committed secrets from the working tree and close the .gitignore gap

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 56f4d65..HEAD -- nav-invoice/certs banking/enablebanking.pem banking/public.crt banking/redister.sh banking/.gitignore uploader/.gitignore .gitignore`
> If any in-scope file changed since this plan was written, compare the
> "Current state" section against the live files before proceeding; on a
> mismatch, treat it as a STOP condition.
>
> **Important — this plan has two parts with different owners.** Part A (git
> hygiene: removing tracked secret files, adding `.gitignore` rules) is
> executor-actionable and is the actual scope of this plan. Part B (rotating
> the underlying credentials at NAV, Google, and Enable Banking) requires a
> human with access to those external portals — an executor model cannot do
> this. Part B is listed as a checklist for the human operator; do not attempt
> to call any external API or portal to "rotate" anything yourself.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (file removal + .gitignore only)
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `56f4d65`, 2026-07-16

## Why this matters

Real, non-placeholder secret material is currently tracked in this git
repository:

- `nav-invoice/certs/key.pem` — an RSA private key used to sign NAV Online
  Számla API requests (mTLS/signing key for this taxpayer's NAV technical
  user), still present in the working tree today.
- `banking/enablebanking.pem` — an RSA private key registered with the
  Enable Banking API, still present in the working tree today.
- `banking/redister.sh` — has a Firebase/Google-issued JWT bearer token
  hardcoded directly in a `curl` command.
- Additionally, `graphtrek-gmail/credentials.json`, `graphtrek-gmail/token.json`
  (Google OAuth client secret + Gmail refresh token) and `nav-szamla/.env`
  (NAV username/password/keys) were committed at `8f0d619` (2026-06-10) and,
  while later directory renames (`graphtrek-gmail` → `attachment-downloader`,
  `nav-szamla` → `nav-invoice`) removed them from the current working tree,
  the original blobs are still fully retrievable from git history (e.g.
  `git show 8f0d619:nav-szamla/.env`).

This repo is a **private** GitHub repo (confirmed via `gh repo view --json
visibility`), which lowers urgency relative to a public leak, but repo access
still exists (collaborators, any future fork, any future switch to public),
and git history doesn't expire on its own. The fix has two independent
pieces: stop the currently-tracked files from being tracked (this plan, Part
A), and rotate the underlying credentials so the historical exposure stops
mattering (Part B, human-only).

## Current state

Files confirmed via `git ls-files` to be currently tracked:

```
banking/enablebanking.pem
banking/public.crt
banking/redister.sh
nav-invoice/certs/cert.pem
nav-invoice/certs/key.pem
```

`banking/redister.sh` (full contents — the bearer token is already expired
per its `exp` claim, decoded without printing the token value):

```bash
curl -X POST -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"test\",\"certificate\":\"$(cat public.crt | tr '\n' '|' | sed 's/|/\\n/g')\",\"environment\":\"SANDBOX\",\"redirect_urls\":[\"https://localhost:8004/\"]}" \
  https://enablebanking.com/api/applications
```

Root `.gitignore` (relevant lines only):

```
# Environment & secrets
.env
token.json
credentials.json
...
wise/wise_sca_private.pem
wise/wise_sca_public.pem
```

Note the pattern: `wise/` has its own `.gitignore` with a blanket `*.pem`
rule (see exemplar below), but `nav-invoice/`, `banking/`, and `uploader/` do
not — that inconsistency is why `nav-invoice/certs/*.pem` and
`banking/enablebanking.pem` slipped through.

**Exemplar to follow** — `wise/.gitignore` (already correct, copy this
shape):

```
.env
*.pem
wise_browser_session.json
logs/
balance-statements/
__pycache__/
*.pyc
.venv/
```

`nav-invoice/certs/` currently has no `.gitignore` of its own, and neither
`banking/` nor `uploader/` has one at all.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Confirm current tracked secrets | `git ls-files \| grep -E "\.pem$\|\.crt$\|redister\.sh"` | Lists the 5 files above (before this plan) |
| Verify removal | `git ls-files \| grep -E "\.pem$\|\.crt$\|redister\.sh"` | Empty output (after this plan) |
| Confirm files still exist locally (untracked, not deleted from disk) | `ls nav-invoice/certs/ banking/` | Files still present on disk, just untracked |

## Scope

**In scope** (the only files you should create/modify/remove from tracking):
- `nav-invoice/.gitignore` (create)
- `banking/.gitignore` (create)
- `uploader/.gitignore` (create)
- Removing from git tracking (`git rm --cached`, NOT `git rm`, so the files
  stay on disk for the operator to use locally): `nav-invoice/certs/key.pem`,
  `nav-invoice/certs/cert.pem`, `banking/enablebanking.pem`,
  `banking/public.crt`
- `banking/redister.sh` — rewrite to read the bearer token from an
  environment variable instead of a hardcoded literal (keep the script
  tracked; only the secret literal is the problem)

**Out of scope** (do NOT touch):
- Do not attempt to rewrite git history (`git filter-repo`, BFG, force-push).
  That is a separate, higher-risk decision for the repository owner given
  the repo is private and has collaborators/CI that would need to
  re-clone — flag it in your final report as a follow-up decision, do not
  do it.
- Do not rotate any credentials yourself (see Part B below — human-only).
- Do not modify `wise/.gitignore` (already correct).
- Do not touch any other service's `.env`, keys, or auth code.

## Git workflow

- Branch: `advisor/001-credential-hygiene`
- One commit for the `.gitignore` additions + `git rm --cached`, message
  style matching this repo's observed convention (short imperative, e.g.
  `chore: stop tracking committed private keys, add .gitignore coverage`
  — matches the style of commit `136a35e` in `git log`).
- Do NOT push or open a PR unless the operator instructs it.

## Steps

### Step 1: Add `.gitignore` to `nav-invoice/`

Create `nav-invoice/.gitignore`:

```
.env
certs/*.pem
logs/
__pycache__/
*.pyc
.venv/
```

**Verify**: `cat nav-invoice/.gitignore` → file exists with the content above.

### Step 2: Add `.gitignore` to `banking/` and `uploader/`

Create `banking/.gitignore` and `uploader/.gitignore`, each with:

```
.env
*.pem
*.key
*.crt
logs/
__pycache__/
*.pyc
.venv/
```

**Verify**: `ls banking/.gitignore uploader/.gitignore` → both exist.

### Step 3: Untrack the committed secret files (keep them on disk)

```bash
git rm --cached nav-invoice/certs/key.pem nav-invoice/certs/cert.pem banking/enablebanking.pem banking/public.crt
```

**Verify**: `git status` shows these 4 files as "deleted" (staged) but
`ls nav-invoice/certs/ banking/` shows they still exist on disk untracked.
`git ls-files | grep -E "\.pem$|\.crt$"` returns empty.

### Step 4: Rewrite `banking/redister.sh` to not hardcode the bearer token

Replace the hardcoded `Authorization: Bearer <token>` header with a read
from an environment variable, e.g.:

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${ENABLEBANKING_REGISTER_TOKEN:?Set ENABLEBANKING_REGISTER_TOKEN before running this script}"

curl -X POST -H "Authorization: Bearer ${ENABLEBANKING_REGISTER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"test\",\"certificate\":\"$(cat public.crt | tr '\n' '|' | sed 's/|/\\n/g')\",\"environment\":\"SANDBOX\",\"redirect_urls\":[\"https://localhost:8004/\"]}" \
  https://enablebanking.com/api/applications
```

**Verify**: `grep -c "Bearer \${ENABLEBANKING_REGISTER_TOKEN}" banking/redister.sh` → `1`; `grep -c "eyJ"  banking/redister.sh` → `0` (no literal JWT remains).

### Step 5: Commit

```bash
git add nav-invoice/.gitignore banking/.gitignore uploader/.gitignore banking/redister.sh
git rm --cached nav-invoice/certs/key.pem nav-invoice/certs/cert.pem banking/enablebanking.pem banking/public.crt
git commit -m "chore: stop tracking committed private keys, add .gitignore coverage"
```

**Verify**: `git status` → clean (nothing to commit); `git show --stat HEAD` shows the expected file list.

## Test plan

No automated tests apply — this is a git-hygiene change, not application
code. Verification is the `git ls-files` checks in each step above.

## Done criteria

- [ ] `git ls-files | grep -E "\.pem$|\.crt$"` returns empty
- [ ] `nav-invoice/.gitignore`, `banking/.gitignore`, `uploader/.gitignore` all exist
- [ ] `nav-invoice/certs/key.pem`, `nav-invoice/certs/cert.pem`, `banking/enablebanking.pem`, `banking/public.crt` still exist on disk (untracked)
- [ ] `banking/redister.sh` no longer contains a literal JWT
- [ ] `git status` is clean after the commit
- [ ] `plans/README.md` status row updated

## STOP conditions

- If `git rm --cached` reports the files are already untracked (someone beat
  you to this), stop and report — don't re-add the `.gitignore` entries
  redundantly without checking why.
- If `banking/redister.sh` has changed shape since this plan was written
  (drift check), re-read it before editing — don't blindly paste the
  replacement script over unrelated changes.
- Do not proceed to any credential-rotation action (Part B) — that is out of
  scope for an executor and requires the human operator.

## Part B — human-only checklist (report this, do not execute it)

Include this checklist verbatim in your final report to the operator; do not
attempt any of these steps yourself:

- [ ] Rotate the NAV Online Számla technical-user password via the NAV
      portal; reissue the mTLS/signing certificate+key pair; update
      `nav-invoice/.env` (not tracked) with the new password; replace
      `nav-invoice/certs/{key,cert}.pem` locally with the new pair.
- [ ] Revoke the exposed Gmail OAuth refresh token via Google Account →
      Security → Third-party access; rotate the OAuth client secret in
      Google Cloud Console; regenerate `attachment-downloader/credentials.json`
      and `token.json` locally (both already gitignored).
- [ ] Regenerate the Enable Banking RSA keypair via their dashboard;
      re-register the new public key; replace `banking/enablebanking.pem`
      locally.
- [ ] Decide whether to rewrite git history to purge the old blobs
      (`8f0d619` and the still-tracked `.pem` files' history) — only
      necessary if the repo's private status or collaborator list changes,
      or out of an abundance of caution. This is disruptive (requires
      force-push + everyone re-cloning) and optional given rotation above
      makes the old values inert.

## Maintenance notes

- Anyone adding a new sub-project to this workspace should copy a
  `.gitignore` with at minimum `.env`, `*.pem`, `*.key`, `logs/`,
  `__pycache__/`, `.venv/` — this workspace's per-project `.gitignore`
  convention (see `wise/.gitignore`) is not yet applied uniformly; this plan
  only closes the gap for the two directories that had live secrets.
- A reviewer should confirm the 4 untracked files are still present locally
  before merging (so nothing breaks at runtime) — `git rm --cached` does not
  delete the working-tree copy, but it's worth a sanity check.
