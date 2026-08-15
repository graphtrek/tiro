"""FastAPI app az auth mikroszervizhez (port 8007)."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from auth_service.config import configure_logging, get_settings
from auth_service.models import (
    AuthError,
    ForbiddenError,
    JWTClaims,
    NotAllowedError,
    ProviderInfo,
    TokenPair,
    UserInfo,
)
from auth_service.service import AuthService

_settings = get_settings()
configure_logging(_settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Auth - Központi Authentication Mikroszerviz",
    description=(
        "Google OAuth 2.0 / OpenID Connect belépés; saját kiállítású RS256 JWT "
        "(access + refresh). A védett mikroszervizek a /.well-known/jwks.json "
        "kulcsaival lokálisan validálnak."
    ),
    version="0.1.0",
)

# A vision login oldala fetch-csel hívja a /auth/refresh végpontot (silent login).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_settings.vision_url.rstrip("/")],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_service: AuthService | None = None


def get_service() -> AuthService:
    """Lustán inicializált singleton — az első hívás friss RS256 kulcspárt generál,
    így egy szerverindítás (deploy, crash, `--reload`) minden korábban kiadott
    tokent érvénytelenít, és mindenkinek újra be kell lépnie."""
    global _service
    if _service is None:
        _service = AuthService(regenerate_keys=True)
    return _service


security = HTTPBearer(auto_error=False)


def _extract_token(
    request: Request, credentials: HTTPAuthorizationCredentials | None
) -> str | None:
    if credentials:
        return credentials.credentials
    return request.cookies.get(get_settings().access_cookie_name)


def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    service: AuthService = Depends(get_service),
) -> JWTClaims:
    token = _extract_token(request, credentials)
    if not token:
        raise HTTPException(status_code=401, detail="Hiányzó access token")
    try:
        return service.verify_access_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    path = request.url.path
    logger.info(
        "%s %s → %d in %.0fms", request.method, path, response.status_code, elapsed_ms
    )
    return response


# -- publikus végpontok ------------------------------------------------------


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}


@app.get("/.well-known/jwks.json")
def jwks(service: AuthService = Depends(get_service)):
    """Publikus kulcsok a JWT lokális validálásához (kid-del, rotáció támogatott)."""
    return service.jwt.jwks()


@app.get("/auth/providers", response_model=list[ProviderInfo])
def providers(service: AuthService = Depends(get_service)):
    """Engedélyezett providerek listája a login oldalhoz."""
    return service.provider_infos()


@app.get("/auth/{provider}/login")
def login(
    provider: str,
    next: str | None = None,
    service: AuthService = Depends(get_service),
):
    """OAuth flow indítása → 302 redirect a providerhez (state + PKCE)."""
    try:
        authorize_url = service.start_login(provider, next_url=next)
    except AuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(authorize_url, status_code=302)


def _login_error_redirect(message: str) -> RedirectResponse:
    settings = get_settings()
    url = f"{settings.vision_url.rstrip('/')}/login?error={quote(message)}"
    return RedirectResponse(url, status_code=302)


def _set_token_cookies(response: Response, tokens: TokenPair) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.access_cookie_name,
        tokens.access_token,
        max_age=settings.access_token_ttl,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        settings.refresh_cookie_name,
        tokens.refresh_token,
        max_age=settings.refresh_token_ttl,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        # host szintű path: a vision /logout így tudja továbbítani visszavonásra
        path="/",
    )


@app.get("/auth/{provider}/callback")
def callback(
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    service: AuthService = Depends(get_service),
):
    """OAuth callback a providertől → token kiállítás, cookie, 302 a `next`-re."""
    if error:
        return _login_error_redirect(f"A belépés megszakadt: {error}")
    if not code or not state:
        return _login_error_redirect("Hiányzó code vagy state paraméter")
    try:
        tokens, _user, next_url = service.complete_login(provider, code=code, state=state)
    except NotAllowedError as exc:
        return _login_error_redirect(str(exc))
    except AuthError as exc:
        logger.warning("Sikertelen belépés (%s): %s", provider, exc)
        return _login_error_redirect(str(exc))

    response = RedirectResponse(next_url, status_code=302)
    _set_token_cookies(response, tokens)
    return response


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


@app.post("/auth/refresh", response_model=TokenPair)
def refresh(
    request: Request,
    body: RefreshRequest | None = None,
    service: AuthService = Depends(get_service),
):
    """Access token frissítése refresh tokennel (cookie vagy JSON body)."""
    settings = get_settings()
    token = (body.refresh_token if body else None) or request.cookies.get(
        settings.refresh_cookie_name
    )
    if not token:
        raise HTTPException(status_code=401, detail="Hiányzó refresh token")
    try:
        tokens = service.refresh(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    response = Response(content=tokens.model_dump_json(), media_type="application/json")
    response.set_cookie(
        settings.access_cookie_name,
        tokens.access_token,
        max_age=settings.access_token_ttl,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


class VerifyRequest(BaseModel):
    token: str


@app.post("/auth/verify")
def verify(body: VerifyRequest, service: AuthService = Depends(get_service)):
    """Token introspekció (opcionális; a szervizek normál esetben lokálisan validálnak)."""
    try:
        claims = service.verify_access_token(body.token)
        return {"active": True, "claims": claims.model_dump()}
    except AuthError as exc:
        return {"active": False, "error": str(exc)}


# -- védett végpontok --------------------------------------------------------


@app.get("/auth/me", response_model=UserInfo)
def me(claims: JWTClaims = Depends(require_auth)):
    """A bejelentkezett felhasználó adatai."""
    return UserInfo(
        sub=claims.sub,
        email=claims.email or "",
        name=claims.name,
        picture=claims.picture,
        provider=claims.provider or "unknown",
    )


@app.post("/auth/logout")
def logout(
    request: Request,
    _claims: JWTClaims = Depends(require_auth),
    service: AuthService = Depends(get_service),
):
    """Cookie törlés + a refresh token `jti`-jének visszavonása."""
    settings = get_settings()
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    revoked_jti = service.revoke_refresh_token(refresh_token) if refresh_token else None

    response = Response(content='{"status": "logged_out"}', media_type="application/json")
    response.delete_cookie(settings.access_cookie_name, path="/")
    response.delete_cookie(settings.refresh_cookie_name, path="/")
    if revoked_jti:
        logger.info("Refresh token visszavonva: jti=%s", revoked_jti)
    return response


class ImpersonateRequest(BaseModel):
    email: str


@app.post("/auth/impersonate", response_model=TokenPair)
def impersonate(
    body: ImpersonateRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    claims: JWTClaims = Depends(require_auth),
    service: AuthService = Depends(get_service),
):
    """Admin belép egy másik felhasználóként — csak `ADMIN_EMAILS` tagoknak."""
    admin_token = _extract_token(request, credentials)
    try:
        tokens = service.impersonate(claims, body.email, admin_token)
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    settings = get_settings()
    response = Response(content=tokens.model_dump_json(), media_type="application/json")
    # csak az access cookie-t írjuk felül — az admin refresh cookie-ja érintetlen marad
    response.set_cookie(
        settings.access_cookie_name,
        tokens.access_token,
        max_age=tokens.expires_in,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


@app.get("/settings")
def settings_info(
    _claims: JWTClaims = Depends(require_auth),
    service: AuthService = Depends(get_service),
):
    """Aktív konfiguráció (titkok nélkül)."""
    s = service.settings
    return {
        "enabled_providers": s.enabled_providers_list,
        "oauth_redirect_url": s.oauth_redirect_url,
        "jwt_issuer": s.jwt_issuer,
        "jwt_audience": s.jwt_audience,
        "access_token_ttl": s.access_token_ttl,
        "refresh_token_ttl": s.refresh_token_ttl,
        "allowed_emails": s.allowed_emails_list,
        "allowed_domains": s.allowed_domains_list,
        "vision_url": s.vision_url,
        "cookie_secure": s.cookie_secure,
        "kid": service.jwt.kid,
        "revoked_tokens": len(service.denylist),
        "api_port": s.api_port,
        "log_level": s.log_level,
    }


def run_server():
    import uvicorn

    s = get_settings()
    uvicorn.run("auth_service.api.main:app", host=s.api_host, port=s.api_port, reload=True)


if __name__ == "__main__":
    run_server()
