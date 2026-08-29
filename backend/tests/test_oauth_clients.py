"""Unit tests for the Phase 14.5 OAuth Authorization-Code + PKCE clients
(ADR-022) — `pkce`, `GoogleOAuthClient`, `MicrosoftOAuthClient`.

Plain `httpx.MockTransport`; no network, no OAuth library.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.adapters.oauth.base import decode_jwt_payload
from app.adapters.oauth.errors import OAuthExchangeFailed, OAuthPrincipalUnresolved
from app.adapters.oauth.google import GoogleOAuthClient
from app.adapters.oauth.microsoft import MicrosoftOAuthClient
from app.adapters.oauth.pkce import challenge_for_verifier, generate_pkce_pair, generate_state

# RFC 7636 appendix B worked example.
_RFC7636_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
_RFC7636_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _fake_id_token(*, iss: str, aud: str, email: str) -> str:
    payload = _b64url(json.dumps({"iss": iss, "aud": aud, "email": email}).encode("utf-8"))
    return f"{_b64url(b'{}')}.{payload}.{_b64url(b'sig')}"


# ---------------------------------------------------------------------------
# PKCE
# ---------------------------------------------------------------------------


def test_challenge_for_verifier_matches_rfc7636_vector() -> None:
    assert challenge_for_verifier(_RFC7636_VERIFIER) == _RFC7636_CHALLENGE


def test_generate_pkce_pair_challenge_is_s256_of_its_verifier() -> None:
    pair = generate_pkce_pair()
    assert challenge_for_verifier(pair.verifier) == pair.challenge
    assert "=" not in pair.challenge  # unpadded base64url
    assert 43 <= len(pair.verifier) <= 128


def test_generate_state_is_high_entropy_and_unique() -> None:
    values = {generate_state() for _ in range(50)}
    assert len(values) == 50
    assert all(len(v) >= 32 for v in values)


# ---------------------------------------------------------------------------
# GoogleOAuthClient
# ---------------------------------------------------------------------------


def _google(handler: httpx.MockTransport) -> GoogleOAuthClient:
    return GoogleOAuthClient(
        client_id="google-client-id",
        client_secret="google-secret",
        redirect_uri="http://localhost:8000/oauth/google/callback",
        transport=handler,
    )


def test_google_authorization_url_is_s256_offline_code_flow() -> None:
    url = _google(httpx.MockTransport(lambda _r: httpx.Response(200))).build_authorization_url(
        state="STATE123", code_challenge="CHALLENGE"
    )
    assert "response_type=code" in url
    assert "code_challenge_method=S256" in url
    assert "code_challenge=CHALLENGE" in url
    assert "access_type=offline" in url
    assert "state=STATE123" in url
    assert "gmail.readonly" in url


def test_google_exchange_code_resolves_principal_from_verified_id_token() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/token")
        body = dict(httpx.QueryParams(request.content.decode()))
        assert body["grant_type"] == "authorization_code"
        assert body["code_verifier"] == "VERIFIER"
        return httpx.Response(
            200,
            json={
                "refresh_token": "rt-google",
                "access_token": "at-google",
                "expires_in": 3599,
                "scope": "openid email https://www.googleapis.com/auth/gmail.readonly",
                "id_token": _fake_id_token(
                    iss="https://accounts.google.com", aud="google-client-id", email="Alice@Example.com"
                ),
            },
        )

    tokens = _google(httpx.MockTransport(handle)).exchange_code(code="CODE", code_verifier="VERIFIER")
    assert tokens.refresh_token == "rt-google"
    assert tokens.principal == "alice@example.com"  # lowercased
    assert "https://www.googleapis.com/auth/gmail.readonly" in tokens.granted_scopes


def test_google_exchange_code_rejects_id_token_with_wrong_audience() -> None:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "refresh_token": "rt",
                "access_token": "at",
                "expires_in": 3599,
                "scope": "openid email",
                "id_token": _fake_id_token(
                    iss="https://accounts.google.com", aud="some-other-client", email="a@b.com"
                ),
            },
        )

    with pytest.raises(OAuthPrincipalUnresolved):
        _google(httpx.MockTransport(handle)).exchange_code(code="c", code_verifier="v")


def test_google_exchange_code_without_refresh_token_is_a_failure() -> None:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "at", "expires_in": 10, "scope": "openid"})

    with pytest.raises(OAuthExchangeFailed):
        _google(httpx.MockTransport(handle)).exchange_code(code="c", code_verifier="v")


def test_google_refresh_access_token_returns_fresh_access_token() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        body = dict(httpx.QueryParams(request.content.decode()))
        assert body["grant_type"] == "refresh_token"
        assert body["refresh_token"] == "stored-rt"
        return httpx.Response(200, json={"access_token": "fresh-at", "expires_in": 3600})

    refreshed = _google(httpx.MockTransport(handle)).refresh_access_token("stored-rt")
    assert refreshed.access_token == "fresh-at"
    assert refreshed.expires_in == 3600


def test_google_refresh_invalid_grant_is_flagged() -> None:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant", "error_description": "expired or revoked"})

    with pytest.raises(OAuthExchangeFailed) as excinfo:
        _google(httpx.MockTransport(handle)).refresh_access_token("dead-rt")
    assert excinfo.value.invalid_grant is True


# ---------------------------------------------------------------------------
# MicrosoftOAuthClient
# ---------------------------------------------------------------------------


def _microsoft(handler: httpx.MockTransport) -> MicrosoftOAuthClient:
    return MicrosoftOAuthClient(
        client_id="ms-client-id",
        client_secret="ms-secret",
        redirect_uri="http://localhost:8000/oauth/microsoft/callback",
        tenant="consumers",
        transport=handler,
    )


def test_microsoft_exchange_code_resolves_principal_from_me_endpoint() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(
                200,
                json={
                    "refresh_token": "rt-ms",
                    "access_token": "at-ms",
                    "expires_in": 3600,
                    "scope": "openid email offline_access https://graph.microsoft.com/Mail.Read",
                },
            )
        if request.url.path.endswith("/me"):
            assert request.headers["Authorization"] == "Bearer at-ms"
            return httpx.Response(200, json={"userPrincipalName": "Bob@Contoso.com"})
        raise AssertionError(f"unexpected {request.url}")

    tokens = _microsoft(httpx.MockTransport(handle)).exchange_code(code="c", code_verifier="v")
    assert tokens.refresh_token == "rt-ms"
    assert tokens.principal == "bob@contoso.com"
    assert "https://graph.microsoft.com/Mail.Read" in tokens.granted_scopes


def test_microsoft_authorization_url_uses_configured_tenant_and_s256() -> None:
    url = _microsoft(httpx.MockTransport(lambda _r: httpx.Response(200))).build_authorization_url(
        state="S", code_challenge="C"
    )
    assert "login.microsoftonline.com/consumers/oauth2/v2.0/authorize" in url
    assert "code_challenge_method=S256" in url


def test_decode_jwt_payload_tolerates_a_structurally_broken_token() -> None:
    assert decode_jwt_payload("not-a-jwt") == {}
    assert decode_jwt_payload("a.!!!.c") == {}
