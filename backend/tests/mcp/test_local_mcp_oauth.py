"""End-to-end tests for Alexandria's self-hosted MCP OAuth server."""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import anyio
import httpx
import pytest
from app.mcp_server.backend_api_client import AlexandriaApiClient, AlexandriaApiSettings
from app.mcp_server.local_oauth.contracts import LocalMcpOAuthSettings
from app.mcp_server.local_oauth.local_oauth_enums import (
    LocalOAuthClientConnectionStatus,
)
from app.mcp_server.local_oauth.orm import (
    McpOAuthAuthorizationCodeORM,
    McpOAuthAuthorizationRequestORM,
    McpOAuthClientORM,
    McpOAuthPairingCodeORM,
    McpOAuthTokenORM,
)
from app.mcp_server.local_oauth.provider import LocalMcpOAuthProvider
from app.mcp_server.local_oauth.provider_approval import LocalOAuthApprovalError
from app.mcp_server.local_oauth.repository import LocalMcpOAuthRepository
from app.mcp_server.local_oauth.runtime import LocalMcpOAuthRuntime
from app.mcp_server.server_runtime import build_mcp_server, mcp_transport_security
from app.platform.config.app_config import AppConfig
from app.shared.infrastructure.database import Database
from app.shared.security.secret_cipher import SecretCipher
from fastapi.testclient import TestClient
from mcp.server.auth.provider import AuthorizationParams, TokenError
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from sqlalchemy import select

ISSUER = "http://localhost"
RESOURCE = "http://localhost/mcp"
APPROVAL_KEY = "local-approval-key-with-32-characters"
VERIFIER = "mcp-pkce-verifier-with-enough-entropy-0123456789"
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode("utf-8")).digest())
    .decode("ascii")
    .rstrip("=")
)


def _settings() -> LocalMcpOAuthSettings:
    return LocalMcpOAuthSettings(
        issuer_url=ISSUER,
        resource_url=RESOURCE,
        required_scopes=("alexandria:mcp",),
        default_scopes=("alexandria:mcp", "offline_access"),
        access_token_ttl_seconds=3600,
        refresh_token_ttl_seconds=86400,
        authorization_code_ttl_seconds=300,
        approval_ttl_seconds=600,
        pairing_code_ttl_seconds=300,
        max_approval_attempts=3,
        approval_key=APPROVAL_KEY,
    )


def _client() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        redirect_uris=[AnyUrl("https://chatgpt.com/oauth/callback")],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope="alexandria:mcp offline_access",
        client_name="ChatGPT",
        client_id="client-1",
        client_secret=None,
        client_id_issued_at=1,
        client_secret_expires_at=None,
    )


async def _provider(tmp_path: Path) -> tuple[Database, LocalMcpOAuthProvider]:
    database = Database(
        database_url=os.environ["DATABASE_URL"],
        create_schema=True,
    )
    await database.initialize()
    provider = LocalMcpOAuthProvider(
        repository=LocalMcpOAuthRepository(database.session_factory()),
        secret_cipher=SecretCipher(key=b"x" * 32),
        settings=_settings(),
    )
    return database, provider


def test_local_oauth_provider_issues_rotates_and_revokes_hashed_tokens(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database, provider = await _provider(tmp_path)
        client = _client()
        client.client_secret = "dynamic-client-secret"
        try:
            await provider.register_client(client)
            restored = await provider.get_client("client-1")
            assert restored is not None
            assert restored.client_secret == "dynamic-client-secret"

            approval_url = await provider.authorize(
                client,
                AuthorizationParams(
                    state="state-1",
                    scopes=["alexandria:mcp", "offline_access"],
                    code_challenge=CHALLENGE,
                    redirect_uri=AnyUrl("https://chatgpt.com/oauth/callback"),
                    redirect_uri_provided_explicitly=True,
                    resource=RESOURCE,
                ),
            )
            request_id = parse_qs(urlparse(approval_url).query)["request_id"][0]
            with pytest.raises(LocalOAuthApprovalError, match="invalid"):
                await provider.approve_authorization(
                    request_id=request_id,
                    approval_code="wrong-key",
                )

            pairing = await provider.create_pairing_code()
            redirect_url = await provider.approve_authorization(
                request_id=request_id,
                approval_code=pairing.code,
            )
            redirect_query = parse_qs(urlparse(redirect_url).query)
            code = redirect_query["code"][0]
            assert redirect_query["state"] == ["state-1"]

            second_approval_url = await provider.authorize(
                client,
                AuthorizationParams(
                    state="state-2",
                    scopes=["alexandria:mcp", "offline_access"],
                    code_challenge=CHALLENGE,
                    redirect_uri=AnyUrl("https://chatgpt.com/oauth/callback"),
                    redirect_uri_provided_explicitly=True,
                    resource=RESOURCE,
                ),
            )
            second_request_id = parse_qs(urlparse(second_approval_url).query)[
                "request_id"
            ][0]
            with pytest.raises(LocalOAuthApprovalError, match="invalid"):
                await provider.approve_authorization(
                    request_id=second_request_id,
                    approval_code=pairing.code,
                )

            authorization_code = await provider.load_authorization_code(client, code)
            assert authorization_code is not None
            first_pair = await provider.exchange_authorization_code(
                client,
                authorization_code,
            )
            with pytest.raises(TokenError, match="unavailable"):
                await provider.exchange_authorization_code(client, authorization_code)

            first_access = first_pair.access_token
            first_refresh = first_pair.refresh_token
            assert first_refresh is not None
            assert await provider.load_access_token(first_access) is not None
            loaded_refresh = await provider.load_refresh_token(client, first_refresh)
            assert loaded_refresh is not None

            second_pair = await provider.exchange_refresh_token(
                client,
                loaded_refresh,
                ["alexandria:mcp", "offline_access"],
            )
            assert await provider.load_access_token(first_access) is None
            assert await provider.load_refresh_token(client, first_refresh) is None
            assert (
                await provider.load_access_token(second_pair.access_token) is not None
            )
            second_refresh = second_pair.refresh_token
            assert second_refresh is not None
            loaded_second_refresh = await provider.load_refresh_token(
                client,
                second_refresh,
            )
            assert loaded_second_refresh is not None
            connections = await provider.list_client_connections()
            assert len(connections) == 1
            connected = connections[0]
            assert connected.client_id == "client-1"
            assert connected.client_name == "ChatGPT"
            assert connected.status is LocalOAuthClientConnectionStatus.CONNECTED
            assert connected.connected is True
            assert connected.refresh_token_expires_at is not None
            extended = await provider.extend_client_connection("client-1")
            assert extended is not None
            assert extended.refresh_token_expires_at is not None
            assert (
                extended.refresh_token_expires_at
                == connected.refresh_token_expires_at
                + _settings().refresh_token_ttl_seconds
            )

            async with database.session() as session:
                client_row = await session.get(McpOAuthClientORM, "client-1")
                code_rows = tuple(
                    (await session.execute(select(McpOAuthAuthorizationCodeORM)))
                    .scalars()
                    .all()
                )
                token_rows = tuple(
                    (await session.execute(select(McpOAuthTokenORM))).scalars().all()
                )
                pairing_rows = tuple(
                    (await session.execute(select(McpOAuthPairingCodeORM)))
                    .scalars()
                    .all()
                )
            assert client_row is not None
            assert client_row.client_secret_ciphertext != "dynamic-client-secret"
            assert all(row.code_hash != code for row in code_rows)
            raw_tokens = {
                first_access,
                first_refresh,
                second_pair.access_token,
                second_refresh,
            }
            assert raw_tokens.isdisjoint(row.token_hash for row in token_rows)
            assert len(pairing_rows) == 1
            assert pairing_rows[0].code_hash != pairing.code
            assert pairing_rows[0].consumed_at is not None

            await provider.revoke_token(loaded_second_refresh)
            assert await provider.load_access_token(second_pair.access_token) is None
            revoked_connections = await provider.list_client_connections()
            assert len(revoked_connections) == 1
            assert (
                revoked_connections[0].status
                is LocalOAuthClientConnectionStatus.REGISTERED
            )

            deleted = await provider.delete_client_connection("client-1")
            assert deleted is True
            assert await provider.load_access_token(second_pair.access_token) is None
            assert await provider.get_client("client-1") is None
            assert await provider.list_client_connections() == ()

            async with database.session() as session:
                client_row = await session.get(McpOAuthClientORM, "client-1")
                request_rows = tuple(
                    (await session.execute(select(McpOAuthAuthorizationRequestORM)))
                    .scalars()
                    .all()
                )
                code_rows = tuple(
                    (await session.execute(select(McpOAuthAuthorizationCodeORM)))
                    .scalars()
                    .all()
                )
                token_rows = tuple(
                    (await session.execute(select(McpOAuthTokenORM))).scalars().all()
                )
            assert client_row is None
            assert request_rows == ()
            assert code_rows == ()
            assert token_rows == ()
        finally:
            await database.shutdown()

    anyio.run(scenario)


def test_local_oauth_http_flow_enforces_pkce_and_bearer_auth(tmp_path: Path) -> None:
    async def setup() -> tuple[Database, LocalMcpOAuthRuntime]:
        database, provider = await _provider(tmp_path)
        config = AppConfig(
            _env_file=None,
            mcp_auth_mode="local_oauth2",
            mcp_oauth_issuer=ISSUER,
            mcp_oauth_resource=RESOURCE,
            mcp_local_approval_key=APPROVAL_KEY,
        )
        runtime = LocalMcpOAuthRuntime(
            provider=provider,
            auth_settings=__import__(
                "app.mcp_server.local_oauth.runtime",
                fromlist=["build_local_mcp_oauth_runtime"],
            )
            .build_local_mcp_oauth_runtime(
                config=config,
                database=database,
                secret_cipher=SecretCipher(key=b"x" * 32),
            )
            .auth_settings,
        )
        return database, runtime

    database, runtime = anyio.run(setup)
    backend_client = AlexandriaApiClient(
        AlexandriaApiSettings(base_url="http://backend:8000", timeout=5.0),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    server = build_mcp_server(
        client=backend_client,
        local_oauth_runtime=runtime,
    )
    mcp_app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        host="localhost",
        transport_security=mcp_transport_security("localhost"),
    )
    try:
        with TestClient(mcp_app, base_url=ISSUER) as client:
            registration = client.post(
                "/register",
                json={
                    "redirect_uris": ["https://chatgpt.com/oauth/callback"],
                    "token_endpoint_auth_method": "none",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "scope": "alexandria:mcp offline_access",
                    "client_name": "ChatGPT",
                },
            )
            assert registration.status_code == 201
            client_id = registration.json()["client_id"]

            authorization = client.get(
                "/authorize",
                params={
                    "response_type": "code",
                    "client_id": client_id,
                    "redirect_uri": "https://chatgpt.com/oauth/callback",
                    "scope": "alexandria:mcp offline_access",
                    "state": "state-http",
                    "code_challenge": CHALLENGE,
                    "code_challenge_method": "S256",
                    "resource": RESOURCE,
                },
                follow_redirects=False,
            )
            assert authorization.status_code == 302
            approval_location = authorization.headers["location"]
            request_id = parse_qs(urlparse(approval_location).query)["request_id"][0]
            approval_page = client.get(approval_location)
            assert approval_page.status_code == 200
            assert APPROVAL_KEY not in approval_page.text
            assert 'name="pairing_code"' in approval_page.text
            assert "form-action" not in approval_page.headers["content-security-policy"]
            pairing = anyio.run(runtime.provider.create_pairing_code)

            approval = client.post(
                "/approve",
                data={
                    "request_id": request_id,
                    "pairing_code": pairing.code,
                    "decision": "approve",
                },
                follow_redirects=False,
            )
            assert approval.status_code == 302
            assert approval.headers["location"].startswith(
                "https://chatgpt.com/oauth/callback?"
            )
            assert "content-security-policy" not in approval.headers
            code = parse_qs(urlparse(approval.headers["location"]).query)["code"][0]

            async def pairing_was_consumed() -> bool:
                async with database.session() as session:
                    rows = tuple(
                        (await session.execute(select(McpOAuthPairingCodeORM)))
                        .scalars()
                        .all()
                    )
                return len(rows) == 1 and rows[0].consumed_at is not None

            assert anyio.run(pairing_was_consumed) is True

            bad_token = client.post(
                "/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": "https://chatgpt.com/oauth/callback",
                    "client_id": client_id,
                    "code_verifier": "wrong-verifier",
                    "resource": RESOURCE,
                },
            )
            assert bad_token.status_code == 400
            assert bad_token.json()["error"] == "invalid_grant"

            token = client.post(
                "/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": "https://chatgpt.com/oauth/callback",
                    "client_id": client_id,
                    "code_verifier": VERIFIER,
                    "resource": RESOURCE,
                },
            )
            assert token.status_code == 200
            token_payload = token.json()
            assert token_payload["refresh_token"]

            unauthenticated = client.post("/mcp", json={})
            assert unauthenticated.status_code == 401
            authenticated = client.post(
                "/mcp",
                json={},
                headers={"Authorization": f"Bearer {token_payload['access_token']}"},
            )
            assert authenticated.status_code != 401

            refreshed = client.post(
                "/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": token_payload["refresh_token"],
                    "client_id": client_id,
                    "scope": "alexandria:mcp offline_access",
                    "resource": RESOURCE,
                },
            )
            assert refreshed.status_code == 200
            assert refreshed.json()["access_token"] != token_payload["access_token"]
    finally:
        anyio.run(database.shutdown)
