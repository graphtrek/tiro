#!/usr/bin/env python3
"""Enable Banking client — AIS flow: auth → session → transactions."""

import json
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import jwt
import requests
from cryptography.hazmat.primitives.serialization import load_pem_private_key

BASE_URL = "https://api.enablebanking.com"
APP_ID = "***REMOVED-SECRET***"
REDIRECT_URL = "https://localhost:8004/"
KEY_PATH = Path(__file__).parent / "enablebanking.pem"


def make_jwt(ttl: int = 3600) -> str:
    private_key_bytes = KEY_PATH.read_bytes()
    private_key = load_pem_private_key(private_key_bytes, password=None)
    now = int(time.time())
    payload = {
        "iss": "enablebanking.com",
        "aud": "api.enablebanking.com",
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": APP_ID})


def api(method: str, path: str, token: str, **kwargs) -> dict:
    resp = requests.request(
        method,
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
        **kwargs,
    )
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code} {path}: {resp.text}")
    return resp.json()


def pick_bank(token: str) -> dict:
    print("\nFetching available SANDBOX banks for Hungary (HU)...")
    data = api("GET", "/aspsps", token, params={"country": "HU"})
    banks = data.get("aspsps", [])
    if not banks:
        print("No HU banks found, fetching all...")
        data = api("GET", "/aspsps", token)
        banks = data.get("aspsps", [])

    for i, b in enumerate(banks):
        sandbox = " [SANDBOX]" if b.get("sandbox") else ""
        print(f"  [{i}] {b['name']} ({b['country']}){sandbox}")

    idx = int(input("\nSelect bank number: "))
    bank = banks[idx]
    print(f"\nASPSP details:\n{json.dumps(bank, indent=2)}")
    return bank


def start_auth(token: str, bank: dict) -> str:
    body = {
        "access": {"valid_until": "2026-12-31T23:59:59.000000+00:00"},
        "aspsp": {"name": bank["name"], "country": bank["country"]},
        "state": "moneypenny-test-1",
        "redirect_url": REDIRECT_URL,
        "psu_type": "personal",
    }
    resp = api("POST", "/auth", token, json=body)
    return resp["url"]


def exchange_session(token: str, code: str) -> tuple[str, list]:
    resp = api("POST", "/sessions", token, json={"code": code})
    session_id = resp["session_id"]
    accounts = resp.get("accounts", [])
    return session_id, accounts


def fetch_transactions(token: str, account_uid: str, date_from: str = "2026-01-01") -> list:
    resp = api(
        "GET",
        f"/accounts/{account_uid}/transactions",
        token,
        params={"date_from": date_from},
    )
    return resp.get("transactions", [])


def main():
    token = make_jwt()
    print(f"JWT generated (kid={APP_ID})")

    # Verify app is reachable
    app_info = api("GET", "/application", token)
    print(f"App: {app_info.get('name')} | env={app_info.get('environment')} | active={app_info.get('active')}")

    bank = pick_bank(token)
    print(f"\nStarting auth for {bank['name']} ({bank['country']})...")

    auth_url = start_auth(token, bank)
    print(f"\nOpen this URL in your browser:\n\n  {auth_url}\n")
    webbrowser.open(auth_url)

    print("After bank login you will be redirected to https://localhost:8004/?code=...")
    print("(The browser will show a connection error — that's fine, copy the full URL.)")
    callback = input("\nPaste the full redirect URL (or just the 'code' value): ").strip()

    if callback.startswith("http"):
        parsed = urlparse(callback)
        code = parse_qs(parsed.query).get("code", [None])[0]
    else:
        code = callback

    if not code:
        print("ERROR: could not extract code from input")
        return

    print(f"\nExchanging code for session...")
    session_id, accounts = exchange_session(token, code)
    print(f"Session ID: {session_id}")
    print(f"Accounts ({len(accounts)}):")
    for a in accounts:
        uid = a.get("uid") or a.get("account_id", {}).get("iban", "?")
        iban = a.get("account_id", {}).get("iban", "")
        name = a.get("name", "")
        print(f"  uid={uid}  IBAN={iban}  name={name}")

    if not accounts:
        print("No accounts returned.")
        return

    # Pick first account with a uid
    account = next((a for a in accounts if a.get("uid")), accounts[0])
    uid = account["uid"]
    print(f"\nFetching transactions for account uid={uid}...")

    txns = fetch_transactions(token, uid)
    print(f"\n{len(txns)} transaction(s):\n")
    for t in txns:
        date = t.get("booking_date") or t.get("transaction_date", "?")
        amt = t.get("transaction_amount", {})
        amount = f"{amt.get('amount', '?')} {amt.get('currency', '')}"
        cdr = t.get("credit_debit_indicator", "")
        sign = "+" if cdr == "CRDT" else "-"
        info = (t.get("remittance_information") or [""])[0]
        creditor = (t.get("creditor") or {}).get("name", "")
        debtor = (t.get("debtor") or {}).get("name", "")
        counterpart = creditor or debtor
        print(f"  {date}  {sign}{amount:>18}  {counterpart or info}")

    print("\nDone. Session ID for future calls:", session_id)


if __name__ == "__main__":
    main()
