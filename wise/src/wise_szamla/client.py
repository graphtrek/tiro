"""Wise API HTTP kliens."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import Settings, get_settings
from .models import WiseStatement

logger = logging.getLogger(__name__)


class WiseApiError(RuntimeError):
    """Wise API hívás sikertelen."""


class WiseClient:
    """Wise REST API kliens.

    Támogatja a live és sandbox környezeteket, automatikus újrapróbálással.
    """

    LIVE_URL = "https://api.wise.com"
    SANDBOX_URL = "https://api.sandbox.transferwise.tech"

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.base_url = (
            self.SANDBOX_URL if self.settings.wise_sandbox else self.LIVE_URL
        )
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "Authorization": f"Bearer {self.settings.wise_api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        retry = Retry(
            total=self.settings.max_retries,
            backoff_factor=self.settings.retry_delay,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        return session

    # ── Publikus metódusok ────────────────────────────────────────────────────

    def get_profiles(self) -> List[Dict[str, Any]]:
        """Visszaadja a hitelesített felhasználó profillistáját."""
        return self._get("/v2/profiles").json()

    def get_balances(self) -> List[Dict[str, Any]]:
        """Visszaadja a profil borderless számla egyenlegeit.

        Wise v1 borderless-accounts API-t használ, amely minden
        account-típusnál elérhető (szemben a v2 /balances végponttal).
        """
        account = self._get_borderless_account()
        return account.get("balances", [])

    def get_statement(
        self,
        start_date: str,
        end_date: str,
        currency: Optional[str] = None,
    ) -> WiseStatement:
        """Letölti a megadott pénznemű bankszámlakivonatot.

        Args:
            start_date: Kezdő dátum (YYYY-MM-DD)
            end_date:   Záró dátum (YYYY-MM-DD)
            currency:   Pénznem (pl. EUR); default: WISE_ACCOUNT_CURRENCY

        Returns:
            Parszolt :class:`WiseStatement` objektum.
        """
        currency = (currency or self.settings.wise_account_currency).upper()
        profile_id = self.settings.wise_profile_id
        balance_id = self._get_balance_id_for_currency(currency)

        params = {
            "intervalStart": f"{start_date}T00:00:00.000Z",
            "intervalEnd": f"{end_date}T23:59:59.999Z",
        }
        t0 = time.monotonic()
        resp = self._get(
            f"/v1/profiles/{profile_id}/balance-statements/{balance_id}/statement.json",
            params=params,
        )
        elapsed_ms = (time.monotonic() - t0) * 1000
        statement = WiseStatement.model_validate(resp.json())
        logger.info(
            "Wise statement %s..%s (%s, balance_id=%s): %d tranzakció %.0fms alatt",
            start_date,
            end_date,
            currency,
            balance_id,
            len(statement.transactions),
            elapsed_ms,
        )
        return statement

    # ── Belső segédek ────────────────────────────────────────────────────────

    def _get_borderless_account(self) -> Dict[str, Any]:
        """Visszaadja a profil első borderless számláját (v1 API)."""
        profile_id = self.settings.wise_profile_id
        accounts = self._get(
            "/v1/borderless-accounts",
            params={"profileId": profile_id},
        ).json()
        if not accounts:
            raise WiseApiError(
                f"Nem található borderless számla a {profile_id} profil alatt."
            )
        return accounts[0]

    def _get_balance_id_for_currency(self, currency: str) -> int:
        """Visszaadja a megadott pénznemhez tartozó balance ID-t."""
        account = self._get_borderless_account()
        for b in account.get("balances", []):
            if b.get("currency") == currency:
                return b["id"]
        available = [b.get("currency") for b in account.get("balances", [])]
        raise WiseApiError(
            f"Nem található {currency} egyenleg. Elérhető pénznemek: {available}"
        )

    def _sign_sca(self, otp: str) -> str:
        """RSA-SHA256 aláírás a Wise SCA OTP-hez."""
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        import base64

        key_path = self.settings.wise_sca_private_key_path
        if not key_path:
            raise WiseApiError(
                "Wise SCA hitelesítés szükséges a kivonatok letöltéséhez. "
                "Hozz létre RSA kulcspárt, regisztráld a nyilvános kulcsot a Wise API "
                "beállításokban, majd add meg a privát kulcs elérési útját: "
                "WISE_SCA_PRIVATE_KEY_PATH=./wise_sca_private.pem"
            )
        with open(key_path, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
        signature = private_key.sign(otp.encode(), padding.PKCS1v15(), hashes.SHA256())
        return base64.b64encode(signature).decode()

    def _get(self, path: str, params: Optional[dict] = None) -> requests.Response:
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.get(
                url, params=params, timeout=self.settings.request_timeout
            )

            # Wise SCA challenge: sign the OTP and retry once
            if resp.status_code == 403 and "x-2fa-approval" in resp.headers:
                otp = resp.headers["x-2fa-approval"]
                logger.debug("Wise SCA challenge: signing OTP %s", otp)
                signature = self._sign_sca(otp)
                resp = self.session.get(
                    url,
                    params=params,
                    timeout=self.settings.request_timeout,
                    headers={"x-2fa-approval": otp, "x-signature": signature},
                )

            # Tartós SCA elutasítás: EU/UK-ban a personal token nem férhet a
            # kivonat végponthoz (PSD2). Magyarázat a néma 403 helyett.
            if (
                resp.status_code == 403
                and resp.headers.get("x-2fa-approval-result") == "REJECTED"
            ):
                logger.error(
                    "Wise SCA elutasítva (403, x-2fa-approval-result=REJECTED) a(z) %s "
                    "végponton. EU/UK-ban a kivonat-hozzáférés (balance-statements) PSD2 "
                    "miatt NEM érhető el personal tokennel — OAuth 2.0-t kell használni "
                    "personal token helyett. A client_id + client_secret a Wise Platform "
                    "partnerprogramon keresztül igényelhető a Wise-tól (sales/CSM). "
                    "Alternatíva: a kivonat kézi CSV exportja a Wise webfelületéről.",
                    path,
                )

            resp.raise_for_status()
        except requests.HTTPError as exc:
            body = exc.response.text[:300] if exc.response is not None else ""
            status = exc.response.status_code if exc.response is not None else "?"
            raise WiseApiError(
                f"Wise API HTTP {status} {path}: {body}"
            ) from exc
        except requests.RequestException as exc:
            raise WiseApiError(f"Wise API kapcsolati hiba {path}: {exc}") from exc
        return resp
