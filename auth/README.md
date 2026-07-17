# Auth – Központi Authentication Mikroszerviz (port 8007)

Google OAuth 2.0 / OpenID Connect belépés a Moneypenny rendszerhez. Sikeres
belépés után saját kiállítású **RS256 JWT**-t ad (access + refresh); a többi
mikroszerviz soha nem hívja a Google-t, kizárólag a JWT-t validálja lokálisan a
`/.well-known/jwks.json` publikus kulcsaival.

Nincs saját adatbázisa — minden sikeres bejelentkezéskor best-effort elmenti a
felhasználó profilját és a login providert az `invoice-core` (:8004)
`POST /api/v1/users` végpontján (a frissen kiállított access tokennel). Ha az
invoice-core nem érhető el, a hiba csak logolva van, a bejelentkezés nem hiúsul
meg. Bázis URL: `INVOICE_CORE_URL` (`.env`).

Specifikáció: `../moneypenny/auth-service-spec.md`

> **Jelenlegi állapot**: minden védett szerviz `.env`-jében `AUTH_ENABLED=false`
> — a védelem bekapcsolásához előbb a Google OAuth-ot kell beállítani (lásd
> lent), majd szervizenként `AUTH_ENABLED=true`-ra állítani a kapcsolót.

## Beüzemelés

```bash
cd auth
uv sync
cp .env.example .env            # töltsd ki a GOOGLE_CLIENT_ID / SECRET értékeket
uv run auth keygen              # RS256 kulcspár a keys/ könyvtárba (gitignore-olt)

# REST API (port 8007)
python run_api.py
# vagy: uv run uvicorn auth_service.api.main:app --host 0.0.0.0 --port 8007 --reload

# CLI
uv run auth status              # konfiguráció + kulcsok + providerek állapota
uv run auth verify <token>      # JWT dekódolás + validálás (debug)
uv run auth revoke <jti>        # refresh token visszavonása
uv run auth providers           # engedélyezett providerek

# Tesztek
uv run pytest tests/ -v
```

## Google Cloud beállítás

1. Google Cloud Console → APIs & Services → Credentials → **OAuth 2.0 Client ID** (Web application).
2. Authorized redirect URI: `http://localhost:8007/auth/google/callback`.
3. A kapott client ID / secret a `.env`-be kerül.

## Végpontok

| Method | Endpoint | Auth | Leírás |
|---|---|---|---|
| `GET` | `/health` | – | állapotellenőrzés |
| `GET` | `/.well-known/jwks.json` | – | JWT publikus kulcsok (JWKS) |
| `GET` | `/auth/providers` | – | engedélyezett providerek a login oldalhoz |
| `GET` | `/auth/{provider}/login?next=` | – | OAuth flow indítása → 302 |
| `GET` | `/auth/{provider}/callback` | – | OAuth callback → cookie + 302 `next` |
| `POST` | `/auth/refresh` | refresh token | új access token |
| `POST` | `/auth/verify` | – | token introspekció |
| `POST` | `/auth/logout` | ✅ | cookie törlés + refresh token visszavonás |
| `GET` | `/auth/me` | ✅ | bejelentkezett felhasználó |
| `GET` | `/settings` | ✅ | aktív konfiguráció (titkok nélkül) |

## Védett szervizek

Minden mikroszerviz azonos mintát követ — egy kis, projektenként bemásolt
`auth.py` modul (`jwt_auth.py` a nav-invoice-ban) app szintű dependency-ként,
csak a `GET /health` publikus. A vision middleware-t használ: böngészős
oldalaknál `302 → /login`, API hívásnál `401`. A vision és az invoice-core a
beérkező Bearer tokent továbbadja a downstream hívásokban (token passthrough).
Szervizenkénti kapcsolók: `AUTH_ENABLED`, `AUTH_SERVICE_URL`.
