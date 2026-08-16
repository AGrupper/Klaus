"""OAuth 2.1 authorization service for Klaus remote MCP connectors.

Klaus is both the authorization server and the protected resource server. The
user identity is established by the existing Google-backed Hub session; this
module handles public-client registration, authorization-code + PKCE exchange,
short-lived access tokens, refresh rotation, and revocation.

Only hashes of bearer credentials are persisted. Interactive and routine MCP
resources are intentionally separate audiences with non-overlapping approval
and unattended-routine authorities.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from mcp.server.auth.provider import AccessToken


ALL_SCOPES = frozenset(
    {"klaus.read", "klaus.write", "klaus.memory", "klaus.routine", "klaus.approve"}
)
INTERACTIVE_SCOPES = frozenset(
    {"klaus.read", "klaus.write", "klaus.memory", "klaus.approve"}
)
ROUTINE_SCOPES = frozenset(
    {"klaus.read", "klaus.write", "klaus.memory", "klaus.routine"}
)


class OAuthRequestError(Exception):
    """OAuth protocol error safe to return to a public client."""

    def __init__(self, error: str, description: str, status_code: int = 400) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code


class OAuthStore(Protocol):
    """Persistence contract used by the authorization service."""

    def put_client(self, client_id: str, record: dict[str, Any]) -> None: ...
    def get_client(self, client_id: str) -> dict[str, Any] | None: ...
    def put_code(self, digest: str, record: dict[str, Any]) -> None: ...
    def get_code(self, digest: str) -> dict[str, Any] | None: ...
    def consume_code(self, digest: str) -> dict[str, Any] | None: ...
    def put_access(self, digest: str, record: dict[str, Any]) -> None: ...
    def get_access(self, digest: str) -> dict[str, Any] | None: ...
    def put_refresh(self, digest: str, record: dict[str, Any]) -> None: ...
    def get_refresh(self, digest: str) -> dict[str, Any] | None: ...
    def consume_refresh(self, digest: str) -> dict[str, Any] | None: ...
    def revoke(self, digest: str) -> None: ...


class InMemoryOAuthStore:
    """Thread-safe store used by protocol tests and local development."""

    def __init__(self) -> None:
        self.clients: dict[str, dict[str, Any]] = {}
        self.codes: dict[str, dict[str, Any]] = {}
        self.access: dict[str, dict[str, Any]] = {}
        self.refresh_tokens: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def put_client(self, client_id: str, record: dict[str, Any]) -> None:
        with self._lock:
            self.clients[client_id] = dict(record)

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        record = self.clients.get(client_id)
        return dict(record) if record else None

    def put_code(self, digest: str, record: dict[str, Any]) -> None:
        with self._lock:
            self.codes[digest] = dict(record)

    def get_code(self, digest: str) -> dict[str, Any] | None:
        record = self.codes.get(digest)
        return dict(record) if record else None

    def consume_code(self, digest: str) -> dict[str, Any] | None:
        with self._lock:
            record = self.codes.get(digest)
            if not record or record.get("consumed"):
                return None
            record = {**record, "consumed": True}
            self.codes[digest] = record
            return dict(record)

    def put_access(self, digest: str, record: dict[str, Any]) -> None:
        with self._lock:
            self.access[digest] = dict(record)

    def get_access(self, digest: str) -> dict[str, Any] | None:
        record = self.access.get(digest)
        return dict(record) if record else None

    def put_refresh(self, digest: str, record: dict[str, Any]) -> None:
        with self._lock:
            self.refresh_tokens[digest] = dict(record)

    def get_refresh(self, digest: str) -> dict[str, Any] | None:
        record = self.refresh_tokens.get(digest)
        return dict(record) if record else None

    def consume_refresh(self, digest: str) -> dict[str, Any] | None:
        with self._lock:
            record = self.refresh_tokens.get(digest)
            if not record or record.get("consumed"):
                return None
            record = {**record, "consumed": True}
            self.refresh_tokens[digest] = record
            return dict(record)

    def revoke(self, digest: str) -> None:
        with self._lock:
            if digest in self.access:
                self.access[digest] = {**self.access[digest], "revoked": True}
            if digest in self.refresh_tokens:
                self.refresh_tokens[digest] = {
                    **self.refresh_tokens[digest],
                    "revoked": True,
                }


class FirestoreOAuthStore:
    """Cloud Run persistence for OAuth clients and hashed credentials."""

    _COLLECTIONS = {
        "clients": "oauth_clients",
        "codes": "oauth_authorization_codes",
        "access": "oauth_access_tokens",
        "refresh": "oauth_refresh_tokens",
    }

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        from memory.firestore_db import _make_firestore_client

        self._client = _make_firestore_client(project_id, database)

    def _doc(self, kind: str, document_id: str):
        return self._client.collection(self._COLLECTIONS[kind]).document(document_id)

    def _put(self, kind: str, document_id: str, record: dict[str, Any]) -> None:
        stored = dict(record)
        # Firestore TTL requires a timestamp field.  Keep the integer
        # ``expires_at`` protocol value for OAuth comparisons and add a
        # provider-native ``expire_at`` solely for deterministic cleanup.
        expires_at = stored.get("expires_at")
        if kind in {"codes", "access", "refresh"} and expires_at is not None:
            stored["expire_at"] = datetime.fromtimestamp(
                int(expires_at), tz=timezone.utc
            )
        self._doc(kind, document_id).set(stored)

    def _get(self, kind: str, document_id: str) -> dict[str, Any] | None:
        snap = self._doc(kind, document_id).get()
        return dict(snap.to_dict() or {}) if snap.exists else None

    def _consume(self, kind: str, document_id: str) -> dict[str, Any] | None:
        from google.cloud import firestore

        doc = self._doc(kind, document_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def consume_once(txn):
            snap = doc.get(transaction=txn)
            if not snap.exists:
                return None
            record = dict(snap.to_dict() or {})
            if record.get("consumed"):
                return None
            txn.update(doc, {"consumed": True})
            return {**record, "consumed": True}

        return consume_once(transaction)

    def put_client(self, client_id: str, record: dict[str, Any]) -> None:
        self._put("clients", client_id, record)

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        return self._get("clients", client_id)

    def put_code(self, digest: str, record: dict[str, Any]) -> None:
        self._put("codes", digest, record)

    def get_code(self, digest: str) -> dict[str, Any] | None:
        return self._get("codes", digest)

    def consume_code(self, digest: str) -> dict[str, Any] | None:
        return self._consume("codes", digest)

    def put_access(self, digest: str, record: dict[str, Any]) -> None:
        self._put("access", digest, record)

    def get_access(self, digest: str) -> dict[str, Any] | None:
        return self._get("access", digest)

    def put_refresh(self, digest: str, record: dict[str, Any]) -> None:
        self._put("refresh", digest, record)

    def get_refresh(self, digest: str) -> dict[str, Any] | None:
        return self._get("refresh", digest)

    def consume_refresh(self, digest: str) -> dict[str, Any] | None:
        return self._consume("refresh", digest)

    def revoke(self, digest: str) -> None:
        for kind in ("access", "refresh"):
            doc = self._doc(kind, digest)
            if doc.get().exists:
                doc.set({"revoked": True}, merge=True)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _is_safe_redirect(uri: str) -> bool:
    try:
        parsed = urlsplit(uri)
    except ValueError:
        return False
    if parsed.fragment or not parsed.netloc:
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}


@dataclass(slots=True)
class OAuthAuthorizationService:
    """Pure OAuth protocol logic with replaceable persistence."""

    store: OAuthStore
    issuer_url: str
    allowed_subject: str
    access_token_ttl_seconds: int = 3600
    refresh_token_ttl_seconds: int = 30 * 86400
    authorization_code_ttl_seconds: int = 300
    allowed_redirect_hosts: frozenset[str] = frozenset({"claude.ai", "claude.com"})

    def __post_init__(self) -> None:
        self.issuer_url = self.issuer_url.rstrip("/")

    @property
    def interactive_resource(self) -> str:
        return f"{self.issuer_url}/mcp/interactive"

    @property
    def routine_resource(self) -> str:
        return f"{self.issuer_url}/mcp/routine"

    def _allowed_for_resource(self, resource: str) -> frozenset[str]:
        if resource == self.interactive_resource:
            return INTERACTIVE_SCOPES
        if resource == self.routine_resource:
            return ROUTINE_SCOPES
        raise OAuthRequestError("invalid_target", "Unknown MCP resource")

    def register_client(self, metadata: dict[str, Any]) -> dict[str, Any]:
        redirects = metadata.get("redirect_uris")
        if not isinstance(redirects, list) or not redirects:
            raise OAuthRequestError("invalid_client_metadata", "redirect_uris is required")
        if any(not isinstance(uri, str) or not _is_safe_redirect(uri) for uri in redirects):
            raise OAuthRequestError("invalid_redirect_uri", "Redirect URI must use HTTPS")
        for uri in redirects:
            parsed = urlsplit(uri)
            is_local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            if not is_local and parsed.hostname not in self.allowed_redirect_hosts:
                raise OAuthRequestError(
                    "invalid_redirect_uri",
                    "Redirect host is not approved for the Klaus connector",
                )
        if metadata.get("token_endpoint_auth_method", "none") != "none":
            raise OAuthRequestError(
                "invalid_client_metadata", "Only public PKCE clients are supported"
            )
        grants = metadata.get("grant_types", ["authorization_code", "refresh_token"])
        if not set(grants).issubset({"authorization_code", "refresh_token"}):
            raise OAuthRequestError("invalid_client_metadata", "Unsupported grant type")
        responses = metadata.get("response_types", ["code"])
        if responses != ["code"]:
            raise OAuthRequestError("invalid_client_metadata", "Only code response is supported")

        client_id = secrets.token_urlsafe(24)
        now = int(time.time())
        record = {
            "client_id": client_id,
            "client_id_issued_at": now,
            "client_name": str(metadata.get("client_name") or "Claude MCP client")[:200],
            "redirect_uris": list(dict.fromkeys(redirects)),
            "token_endpoint_auth_method": "none",
            "grant_types": list(grants),
            "response_types": ["code"],
        }
        self.store.put_client(client_id, record)
        return record

    def authorize(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        scope: str,
        code_challenge: str,
        code_challenge_method: str,
        resource: str,
        subject: str,
    ) -> dict[str, str]:
        client = self.store.get_client(client_id)
        if not client:
            raise OAuthRequestError("invalid_request", "Unknown client_id")
        if redirect_uri not in client.get("redirect_uris", []):
            raise OAuthRequestError("invalid_request", "redirect_uri does not match registration")
        if code_challenge_method != "S256" or not code_challenge:
            raise OAuthRequestError("invalid_request", "PKCE S256 is required")
        if not hmac.compare_digest(subject.encode(), self.allowed_subject.encode()):
            raise OAuthRequestError("access_denied", "Account is not authorized", 403)

        scopes = scope.split()
        allowed = self._allowed_for_resource(resource)
        if not scopes or "klaus.read" not in scopes or len(scopes) != len(set(scopes)):
            raise OAuthRequestError("invalid_scope", "A unique klaus.read scope is required")
        if not set(scopes).issubset(allowed):
            raise OAuthRequestError("invalid_scope", "Scope is not allowed for this MCP resource")

        code = secrets.token_urlsafe(32)
        self.store.put_code(
            _digest(code),
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scopes": scopes,
                "resource": resource,
                "subject": subject,
                "code_challenge": code_challenge,
                "expires_at": int(time.time()) + self.authorization_code_ttl_seconds,
                "consumed": False,
            },
        )
        return {"code": code}

    def exchange_authorization_code(
        self,
        *,
        code: str,
        client_id: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> dict[str, Any]:
        digest = _digest(code)
        record = self.store.get_code(digest)
        now = int(time.time())
        if (
            not record
            or record.get("consumed")
            or int(record.get("expires_at", 0)) <= now
            or not hmac.compare_digest(str(record.get("client_id", "")), client_id)
            or not hmac.compare_digest(str(record.get("redirect_uri", "")), redirect_uri)
        ):
            raise OAuthRequestError("invalid_grant", "Authorization code is invalid")
        try:
            challenge = _pkce_challenge(code_verifier)
        except (UnicodeEncodeError, ValueError):
            challenge = ""
        if not hmac.compare_digest(str(record.get("code_challenge", "")), challenge):
            raise OAuthRequestError("invalid_grant", "PKCE verification failed")
        consumed = self.store.consume_code(digest)
        if not consumed:
            raise OAuthRequestError("invalid_grant", "Authorization code was already used")
        return self._issue_tokens(consumed)

    def _issue_tokens(self, record: dict[str, Any]) -> dict[str, Any]:
        now = int(time.time())
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(40)
        common = {
            "client_id": record["client_id"],
            "scopes": list(record["scopes"]),
            "resource": record["resource"],
            "subject": record["subject"],
        }
        self.store.put_access(
            _digest(access_token),
            {**common, "expires_at": now + self.access_token_ttl_seconds, "revoked": False},
        )
        self.store.put_refresh(
            _digest(refresh_token),
            {
                **common,
                "expires_at": now + self.refresh_token_ttl_seconds,
                "consumed": False,
                "revoked": False,
            },
        )
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": self.access_token_ttl_seconds,
            "refresh_token": refresh_token,
            "scope": " ".join(common["scopes"]),
        }

    def refresh(self, *, refresh_token: str, client_id: str) -> dict[str, Any]:
        digest = _digest(refresh_token)
        record = self.store.get_refresh(digest)
        now = int(time.time())
        if (
            not record
            or record.get("consumed")
            or record.get("revoked")
            or int(record.get("expires_at", 0)) <= now
            or not hmac.compare_digest(str(record.get("client_id", "")), client_id)
        ):
            raise OAuthRequestError("invalid_grant", "Refresh token is invalid")
        consumed = self.store.consume_refresh(digest)
        if not consumed:
            raise OAuthRequestError("invalid_grant", "Refresh token was already used")
        return self._issue_tokens(consumed)

    def verify_access_token(self, token: str, *, resource: str) -> AccessToken | None:
        record = self.store.get_access(_digest(token))
        now = int(time.time())
        if (
            not record
            or record.get("revoked")
            or int(record.get("expires_at", 0)) <= now
            or not hmac.compare_digest(str(record.get("resource", "")), resource)
            or not hmac.compare_digest(
                str(record.get("subject", "")), self.allowed_subject
            )
        ):
            return None
        return AccessToken(
            token=token,
            client_id=str(record["client_id"]),
            scopes=list(record["scopes"]),
            expires_at=int(record["expires_at"]),
            resource=str(record["resource"]),
            subject=str(record["subject"]),
        )

    def revoke(self, token: str) -> None:
        self.store.revoke(_digest(token))


class KlausTokenVerifier:
    """MCP SDK token verifier pinned to one resource audience."""

    def __init__(self, service: OAuthAuthorizationService, resource: str) -> None:
        self._service = service
        self._resource = resource

    async def verify_token(self, token: str) -> AccessToken | None:
        return self._service.verify_access_token(token, resource=self._resource)


def _redirect_with_query(uri: str, params: dict[str, str]) -> str:
    parsed = urlsplit(uri)
    query = [*parse_qsl(parsed.query, keep_blank_values=True), *params.items()]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def build_oauth_router(
    service: OAuthAuthorizationService,
    subject_resolver: Callable[..., Awaitable[str]],
):
    """Build the OAuth discovery and protocol routes for the Cloud Run app."""
    router = APIRouter()

    def error_response(exc: OAuthRequestError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.error, "error_description": exc.description},
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/.well-known/oauth-authorization-server")
    async def authorization_server_metadata() -> JSONResponse:
        issuer = service.issuer_url
        return JSONResponse(
            content={
                "issuer": issuer,
                "authorization_endpoint": f"{issuer}/oauth/authorize",
                "token_endpoint": f"{issuer}/oauth/token",
                "registration_endpoint": f"{issuer}/oauth/register",
                "revocation_endpoint": f"{issuer}/oauth/revoke",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
                "scopes_supported": sorted(ALL_SCOPES),
            }
        )

    @router.get("/.well-known/oauth-protected-resource/mcp/{kind}")
    async def protected_resource_metadata(kind: str) -> JSONResponse:
        if kind == "interactive":
            resource = service.interactive_resource
            scopes = INTERACTIVE_SCOPES
        elif kind == "routine":
            resource = service.routine_resource
            scopes = ROUTINE_SCOPES
        else:
            return JSONResponse(status_code=404, content={"error": "not_found"})
        return JSONResponse(
            content={
                "resource": resource,
                "authorization_servers": [service.issuer_url],
                "scopes_supported": sorted(scopes),
                "bearer_methods_supported": ["header"],
            }
        )

    @router.post("/oauth/register", status_code=201)
    async def register(request: Request) -> JSONResponse:
        try:
            metadata = await request.json()
            if not isinstance(metadata, dict):
                raise OAuthRequestError(
                    "invalid_client_metadata", "Registration body must be an object"
                )
            return JSONResponse(status_code=201, content=service.register_client(metadata))
        except OAuthRequestError as exc:
            return error_response(exc)

    @router.get("/oauth/authorize")
    async def authorize(
        request: Request,
        subject: str = Depends(subject_resolver),
    ):
        query = request.query_params
        if query.get("response_type") != "code":
            return error_response(
                OAuthRequestError("unsupported_response_type", "Only code is supported")
            )
        state = query.get("state", "")
        if not state:
            return error_response(OAuthRequestError("invalid_request", "state is required"))
        try:
            result = service.authorize(
                client_id=query.get("client_id", ""),
                redirect_uri=query.get("redirect_uri", ""),
                scope=query.get("scope", ""),
                code_challenge=query.get("code_challenge", ""),
                code_challenge_method=query.get("code_challenge_method", ""),
                resource=query.get("resource", ""),
                subject=subject,
            )
        except OAuthRequestError as exc:
            return error_response(exc)
        location = _redirect_with_query(
            query["redirect_uri"], {"code": result["code"], "state": state}
        )
        return RedirectResponse(url=location, status_code=303)

    @router.post("/oauth/token")
    async def token(request: Request) -> JSONResponse:
        form = await request.form()
        try:
            grant_type = str(form.get("grant_type", ""))
            if grant_type == "authorization_code":
                payload = service.exchange_authorization_code(
                    code=str(form.get("code", "")),
                    client_id=str(form.get("client_id", "")),
                    redirect_uri=str(form.get("redirect_uri", "")),
                    code_verifier=str(form.get("code_verifier", "")),
                )
            elif grant_type == "refresh_token":
                payload = service.refresh(
                    refresh_token=str(form.get("refresh_token", "")),
                    client_id=str(form.get("client_id", "")),
                )
            else:
                raise OAuthRequestError(
                    "unsupported_grant_type", "Unsupported grant_type"
                )
            return JSONResponse(
                content=payload,
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )
        except OAuthRequestError as exc:
            return error_response(exc)

    @router.post("/oauth/revoke")
    async def revoke(request: Request) -> JSONResponse:
        form = await request.form()
        supplied_token = str(form.get("token", ""))
        if supplied_token:
            service.revoke(supplied_token)
        # RFC 7009 deliberately returns success even for an unknown token.
        return JSONResponse(content={}, headers={"Cache-Control": "no-store"})

    return router
