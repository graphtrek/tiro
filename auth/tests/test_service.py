"""AuthService tesztek: login flow, whitelist, refresh, revoke."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from auth_service.models import AuthError, ForbiddenError, NotAllowedError, UserInfo
from auth_service.service import AuthService, Denylist
from tests.conftest import FakeInvoiceCoreClient, FakeProvider


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def invoice_core() -> FakeInvoiceCoreClient:
    return FakeInvoiceCoreClient()


@pytest.fixture
def service(settings, jwt_service, provider, invoice_core) -> AuthService:
    return AuthService(
        settings=settings,
        jwt_service=jwt_service,
        providers={"google": provider},
        invoice_core_client=invoice_core,
    )


def _state_from(authorize_url: str) -> str:
    return parse_qs(urlparse(authorize_url).query)["state"][0]


def test_provider_infos(service: AuthService):
    infos = service.provider_infos()
    assert [i.key for i in infos] == ["google"]
    assert infos[0].login_url == "/auth/google/login"


def test_start_login_builds_authorize_url(service: AuthService):
    url = service.start_login("google", next_url="/ui/dashboard")
    query = parse_qs(urlparse(url).query)
    assert query["state"][0] in service._pending
    assert query["code_challenge"][0]
    assert query["redirect_uri"][0] == service.settings.oauth_redirect_url


def test_unknown_provider_rejected(service: AuthService):
    with pytest.raises(AuthError, match="provider"):
        service.start_login("microsoft")


def test_complete_login_happy_path(service: AuthService, provider: FakeProvider):
    state = _state_from(service.start_login("google", next_url="/ui/dashboard"))
    tokens, user, next_url = service.complete_login("google", code="code-1", state=state)

    assert user.email == "imre.tatai@graphtrek.co"
    assert next_url == "http://localhost:8009/ui/dashboard"
    assert provider.exchange_calls[0]["code"] == "code-1"
    # a PKCE verifier a pending bejegyzésből megy át a providerhez
    assert provider.exchange_calls[0]["code_verifier"]

    claims = service.verify_access_token(tokens.access_token)
    assert claims.sub == "google-user-1"


def test_complete_login_saves_user_in_invoice_core(
    service: AuthService, provider: FakeProvider, invoice_core: FakeInvoiceCoreClient
):
    state = _state_from(service.start_login("google"))
    tokens, user, _next_url = service.complete_login("google", code="code-1", state=state)

    assert len(invoice_core.save_calls) == 1
    call = invoice_core.save_calls[0]
    assert call["user"] == user
    assert call["access_token"] == tokens.access_token


def test_complete_login_succeeds_even_if_invoice_core_is_down(
    settings, jwt_service, provider: FakeProvider
):
    failing_client = FakeInvoiceCoreClient(error="connection refused")
    service = AuthService(
        settings=settings,
        jwt_service=jwt_service,
        providers={"google": provider},
        invoice_core_client=failing_client,
    )
    state = _state_from(service.start_login("google"))
    _tokens, user, _next_url = service.complete_login("google", code="code-1", state=state)

    assert user.email == "imre.tatai@graphtrek.co"
    assert failing_client.save_calls  # a hívás megtörtént, de a hiba nem buktatta a belépést


def test_state_is_single_use(service: AuthService):
    state = _state_from(service.start_login("google"))
    service.complete_login("google", code="c", state=state)
    with pytest.raises(AuthError, match="state"):
        service.complete_login("google", code="c", state=state)


def test_invalid_state_rejected(service: AuthService):
    with pytest.raises(AuthError, match="state"):
        service.complete_login("google", code="c", state="nem-letezo")


def test_expired_state_rejected(service: AuthService):
    state = _state_from(service.start_login("google"))
    service._pending[state].created_at -= service.settings.login_state_ttl + 1
    with pytest.raises(AuthError, match="lejárt"):
        service.complete_login("google", code="c", state=state)


def test_whitelist_email_and_domain(service: AuthService):
    assert service.resolve_role("imre.tatai@graphtrek.co") == "read_write"  # explicit e-mail
    assert service.resolve_role("Valaki@Graphtrek.co") == "read_write"  # domain, kis/nagybetű
    with pytest.raises(NotAllowedError):
        service.resolve_role("idegen@gmail.com")


def test_resolve_role_readonly_email_and_domain(service: AuthService):
    assert service.resolve_role("kulso@gmail.com") == "read_only"  # explicit readonly e-mail
    assert service.resolve_role("Valaki@Partner.example") == "read_only"  # readonly domain


def test_resolve_role_unlisted_rejected(service: AuthService):
    with pytest.raises(NotAllowedError):
        service.resolve_role("idegen@gmail.com")


def test_complete_login_sets_readonly_role_for_external_user(
    service: AuthService, provider: FakeProvider
):
    provider.user = UserInfo(sub="ext-1", email="kulso@gmail.com", provider="google")
    state = _state_from(service.start_login("google"))
    tokens, user, _next_url = service.complete_login("google", code="c", state=state)

    assert user.role == "read_only"
    claims = service.verify_access_token(tokens.access_token)
    assert claims.role == "read_only"


def test_refresh_carries_role_through_without_re_resolving(
    service: AuthService, provider: FakeProvider
):
    provider.user = UserInfo(sub="ext-1", email="kulso@gmail.com", provider="google")
    state = _state_from(service.start_login("google"))
    tokens, _user, _next_url = service.complete_login("google", code="c", state=state)

    refreshed = service.refresh(tokens.refresh_token)
    claims = service.verify_access_token(refreshed.access_token)
    assert claims.role == "read_only"


def test_whitelisted_login_rejected(service: AuthService, provider: FakeProvider):
    provider.user = UserInfo(sub="x", email="idegen@gmail.com", provider="google")
    state = _state_from(service.start_login("google"))
    with pytest.raises(NotAllowedError):
        service.complete_login("google", code="c", state=state)


def test_safe_next_url_blocks_open_redirect(service: AuthService):
    assert service._safe_next_url("/ui/bank") == "http://localhost:8009/ui/bank"
    assert service._safe_next_url("https://evil.example/") == "http://localhost:8009"
    assert service._safe_next_url("//evil.example") == "http://localhost:8009"
    assert service._safe_next_url(None) == "http://localhost:8009"


def test_refresh_flow(service: AuthService, provider: FakeProvider):
    tokens = service.issue_tokens(provider.user)
    refreshed = service.refresh(tokens.refresh_token)
    claims = service.verify_access_token(refreshed.access_token)
    assert claims.email == provider.user.email


def test_access_token_not_accepted_as_refresh(service: AuthService, provider: FakeProvider):
    tokens = service.issue_tokens(provider.user)
    with pytest.raises(AuthError):
        service.refresh(tokens.access_token)


def test_revoked_refresh_token_rejected(service: AuthService, provider: FakeProvider):
    tokens = service.issue_tokens(provider.user)
    jti = service.revoke_refresh_token(tokens.refresh_token)
    assert jti
    with pytest.raises(AuthError, match="vissza lett vonva"):
        service.refresh(tokens.refresh_token)


def test_denylist_persists_to_file(settings, jwt_service, provider):
    service = AuthService(
        settings=settings, jwt_service=jwt_service, providers={"google": provider}
    )
    tokens = service.issue_tokens(provider.user)
    service.revoke_refresh_token(tokens.refresh_token)

    reloaded = Denylist(settings.denylist_path)
    assert len(reloaded) == 1


def test_revoke_invalid_token_is_noop(service: AuthService):
    assert service.revoke_refresh_token("nem.jwt.token") is None


def test_impersonate_rejects_non_admin(service: AuthService, invoice_core: FakeInvoiceCoreClient):
    invoice_core.users = [UserInfo(sub="target-1", email="kozma@graphtrek.co", provider="google")]
    admin_claims = service.verify_access_token(
        service.issue_tokens(
            UserInfo(sub="x", email="nem.admin@graphtrek.co", provider="google")
        ).access_token
    )
    with pytest.raises(ForbiddenError):
        service.impersonate(admin_claims, "kozma@graphtrek.co", access_token="tok")


def test_impersonate_rejects_unknown_target(service: AuthService, provider: FakeProvider):
    admin_claims = service.verify_access_token(service.issue_tokens(provider.user).access_token)
    with pytest.raises(AuthError, match="Nincs ilyen"):
        service.impersonate(admin_claims, "ismeretlen@graphtrek.co", access_token="tok")


def test_impersonate_issues_token_with_target_identity_and_impersonator_claims(
    service: AuthService, provider: FakeProvider, invoice_core: FakeInvoiceCoreClient
):
    target = UserInfo(
        sub="target-1", email="kozma@graphtrek.co", name="Kozma Zoltán", provider="google"
    )
    invoice_core.users = [target]
    admin_claims = service.verify_access_token(service.issue_tokens(provider.user).access_token)

    tokens = service.impersonate(admin_claims, "kozma@graphtrek.co", access_token="admin-tok")

    assert tokens.refresh_token is None
    claims = service.verify_access_token(tokens.access_token)
    assert claims.email == "kozma@graphtrek.co"
    assert claims.sub == "target-1"
    assert claims.impersonator_email == provider.user.email
    assert claims.impersonator_sub == provider.user.sub
    assert invoice_core.find_calls[0]["access_token"] == "admin-tok"
