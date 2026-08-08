"""OAuth 2.1/PKCE contract for Klaus's remote MCP resource servers."""
from __future__ import annotations

import base64
import hashlib

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@pytest.fixture()
def oauth_service():
    from interfaces.mcp_oauth import InMemoryOAuthStore, OAuthAuthorizationService

    return OAuthAuthorizationService(
        store=InMemoryOAuthStore(),
        issuer_url="https://klaus.example.com",
        allowed_subject="amit.grupper@gmail.com",
        access_token_ttl_seconds=600,
        refresh_token_ttl_seconds=3600,
    )


def _registered_client(service) -> dict:
    return service.register_client(
        {
            "client_name": "Claude Klaus connector",
            "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        }
    )


def test_dynamic_client_registration_accepts_public_https_client(oauth_service):
    client = _registered_client(oauth_service)

    assert client["client_id"]
    assert client["token_endpoint_auth_method"] == "none"
    assert client["redirect_uris"] == ["https://claude.ai/api/mcp/auth_callback"]


@pytest.mark.parametrize(
    "redirect_uri",
    ["http://claude.ai/callback", "javascript:alert(1)", "https://claude.ai/cb#fragment"],
)
def test_registration_rejects_unsafe_redirects(oauth_service, redirect_uri):
    from interfaces.mcp_oauth import OAuthRequestError

    with pytest.raises(OAuthRequestError) as exc:
        oauth_service.register_client(
            {
                "redirect_uris": [redirect_uri],
                "token_endpoint_auth_method": "none",
            }
        )
    assert exc.value.error == "invalid_redirect_uri"


def test_authorization_code_is_pkce_bound_and_single_use(oauth_service):
    from interfaces.mcp_oauth import OAuthRequestError

    client = _registered_client(oauth_service)
    verifier = "v" * 64
    authorization = oauth_service.authorize(
        client_id=client["client_id"],
        redirect_uri=client["redirect_uris"][0],
        scope="klaus.read klaus.write klaus.memory klaus.approve",
        code_challenge=_challenge(verifier),
        code_challenge_method="S256",
        resource="https://klaus.example.com/mcp/interactive",
        subject="amit.grupper@gmail.com",
    )

    with pytest.raises(OAuthRequestError) as bad_verifier:
        oauth_service.exchange_authorization_code(
            code=authorization["code"],
            client_id=client["client_id"],
            redirect_uri=client["redirect_uris"][0],
            code_verifier="wrong" * 12,
        )
    assert bad_verifier.value.error == "invalid_grant"

    # A failed verifier must not burn the code; the legitimate client can retry.
    token = oauth_service.exchange_authorization_code(
        code=authorization["code"],
        client_id=client["client_id"],
        redirect_uri=client["redirect_uris"][0],
        code_verifier=verifier,
    )
    assert token["token_type"] == "Bearer"
    assert token["expires_in"] == 600
    assert token["scope"] == "klaus.read klaus.write klaus.memory klaus.approve"

    with pytest.raises(OAuthRequestError) as replay:
        oauth_service.exchange_authorization_code(
            code=authorization["code"],
            client_id=client["client_id"],
            redirect_uri=client["redirect_uris"][0],
            code_verifier=verifier,
        )
    assert replay.value.error == "invalid_grant"


def test_routine_scope_can_never_include_approval(oauth_service):
    from interfaces.mcp_oauth import OAuthRequestError

    client = _registered_client(oauth_service)
    with pytest.raises(OAuthRequestError) as exc:
        oauth_service.authorize(
            client_id=client["client_id"],
            redirect_uri=client["redirect_uris"][0],
            scope="klaus.read klaus.write klaus.memory klaus.routine klaus.approve",
            code_challenge=_challenge("x" * 64),
            code_challenge_method="S256",
            resource="https://klaus.example.com/mcp/routine",
            subject="amit.grupper@gmail.com",
        )
    assert exc.value.error == "invalid_scope"


def test_resource_and_scope_sets_are_endpoint_specific(oauth_service):
    from interfaces.mcp_oauth import OAuthRequestError

    client = _registered_client(oauth_service)
    with pytest.raises(OAuthRequestError) as exc:
        oauth_service.authorize(
            client_id=client["client_id"],
            redirect_uri=client["redirect_uris"][0],
            scope="klaus.read klaus.routine",
            code_challenge=_challenge("y" * 64),
            code_challenge_method="S256",
            resource="https://klaus.example.com/mcp/interactive",
            subject="amit.grupper@gmail.com",
        )
    assert exc.value.error == "invalid_scope"


def test_refresh_token_rotates_and_old_token_cannot_be_reused(oauth_service):
    from interfaces.mcp_oauth import OAuthRequestError

    client = _registered_client(oauth_service)
    verifier = "z" * 64
    auth = oauth_service.authorize(
        client_id=client["client_id"],
        redirect_uri=client["redirect_uris"][0],
        scope="klaus.read klaus.write klaus.memory klaus.routine",
        code_challenge=_challenge(verifier),
        code_challenge_method="S256",
        resource="https://klaus.example.com/mcp/routine",
        subject="amit.grupper@gmail.com",
    )
    first = oauth_service.exchange_authorization_code(
        code=auth["code"],
        client_id=client["client_id"],
        redirect_uri=client["redirect_uris"][0],
        code_verifier=verifier,
    )
    second = oauth_service.refresh(
        refresh_token=first["refresh_token"],
        client_id=client["client_id"],
    )

    assert second["refresh_token"] != first["refresh_token"]
    with pytest.raises(OAuthRequestError) as replay:
        oauth_service.refresh(
            refresh_token=first["refresh_token"],
            client_id=client["client_id"],
        )
    assert replay.value.error == "invalid_grant"


def test_token_verification_is_resource_bound_and_revocable(oauth_service):
    client = _registered_client(oauth_service)
    verifier = "a" * 64
    auth = oauth_service.authorize(
        client_id=client["client_id"],
        redirect_uri=client["redirect_uris"][0],
        scope="klaus.read klaus.write klaus.memory klaus.approve",
        code_challenge=_challenge(verifier),
        code_challenge_method="S256",
        resource="https://klaus.example.com/mcp/interactive",
        subject="amit.grupper@gmail.com",
    )
    issued = oauth_service.exchange_authorization_code(
        code=auth["code"],
        client_id=client["client_id"],
        redirect_uri=client["redirect_uris"][0],
        code_verifier=verifier,
    )

    access = oauth_service.verify_access_token(
        issued["access_token"],
        resource="https://klaus.example.com/mcp/interactive",
    )
    assert access is not None
    assert access.subject == "amit.grupper@gmail.com"
    assert access.scopes == ["klaus.read", "klaus.write", "klaus.memory", "klaus.approve"]
    assert oauth_service.verify_access_token(
        issued["access_token"], resource="https://klaus.example.com/mcp/routine"
    ) is None

    oauth_service.revoke(issued["access_token"])
    assert oauth_service.verify_access_token(
        issued["access_token"], resource="https://klaus.example.com/mcp/interactive"
    ) is None


def test_oauth_http_routes_publish_metadata_and_complete_pkce_flow(oauth_service):
    from fastapi import FastAPI
    from interfaces.mcp_oauth import build_oauth_router

    async def allowed_subject() -> str:
        return "amit.grupper@gmail.com"

    app = FastAPI()
    app.include_router(build_oauth_router(oauth_service, allowed_subject))
    client = TestClient(app)

    metadata = client.get("/.well-known/oauth-authorization-server").json()
    assert metadata["issuer"] == "https://klaus.example.com"
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    assert metadata["registration_endpoint"].endswith("/oauth/register")

    protected = client.get(
        "/.well-known/oauth-protected-resource/mcp/interactive"
    ).json()
    assert protected["resource"] == "https://klaus.example.com/mcp/interactive"
    assert "klaus.approve" in protected["scopes_supported"]
    assert "klaus.routine" not in protected["scopes_supported"]

    registration = client.post(
        "/oauth/register",
        json={
            "client_name": "Claude",
            "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert registration.status_code == 201
    registered = registration.json()

    verifier = "b" * 64
    authorization = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": registered["client_id"],
            "redirect_uri": registered["redirect_uris"][0],
            "scope": "klaus.read klaus.write klaus.memory klaus.approve",
            "state": "opaque-client-state",
            "code_challenge": _challenge(verifier),
            "code_challenge_method": "S256",
            "resource": "https://klaus.example.com/mcp/interactive",
        },
        follow_redirects=False,
    )
    assert authorization.status_code == 303
    location = authorization.headers["location"]
    assert location.startswith("https://claude.ai/api/mcp/auth_callback?")
    assert "state=opaque-client-state" in location
    code = location.split("code=", 1)[1].split("&", 1)[0]

    token = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": registered["client_id"],
            "redirect_uri": registered["redirect_uris"][0],
            "code_verifier": verifier,
        },
    )
    assert token.status_code == 200
    assert token.headers["cache-control"] == "no-store"
    assert token.json()["access_token"]


def test_authorize_route_requires_existing_google_backed_subject(oauth_service):
    from fastapi import FastAPI
    from interfaces.mcp_oauth import build_oauth_router

    async def no_session() -> str:
        raise HTTPException(status_code=401, detail={"error": "Not authenticated"})

    app = FastAPI()
    app.include_router(build_oauth_router(oauth_service, no_session))
    client = TestClient(app)
    response = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "missing",
            "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "scope": "klaus.read",
            "state": "s",
            "code_challenge": _challenge("c" * 64),
            "code_challenge_method": "S256",
            "resource": "https://klaus.example.com/mcp/interactive",
        },
    )
    assert response.status_code == 401
