"""MCP OAuth authentication behavior tests."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import anyio
import httpx
from app.mcp_server.http_auth_gate import McpHttpAuthGate
from app.mcp_server.oauth_bearer_verifier import (
    OAuthBearerTokenVerifier,
    OAuthBearerVerifierConfig,
)
from app.mcp_server.protected_resource_metadata import protected_resource_metadata
from app.mcp_server.type_validate.oauth.mcp_auth_enums import McpAuthMode
from app.platform.config.app_config import AppConfig
from app.shared.serialization.orjson_codec import dumps_json
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from starlette.requests import Request


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _jwk_int(value: int) -> str:
    byte_length = (value.bit_length() + 7) // 8
    return _base64url(value.to_bytes(byte_length, "big"))


def _signed_jwt(
    private_key: rsa.RSAPrivateKey,
    claims: dict[str, object],
    kid: str = "test-key",
) -> str:
    header = {"alg": "RS256", "kid": kid}
    signing_input = b".".join(
        [
            _base64url(dumps_json(header)).encode("ascii"),
            _base64url(dumps_json(claims)).encode("ascii"),
        ]
    )
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input.decode('ascii')}.{_base64url(signature)}"


def _jwks(private_key: rsa.RSAPrivateKey, kid: str = "test-key") -> dict[str, object]:
    public_numbers = private_key.public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": kid,
                "alg": "RS256",
                "n": _jwk_int(public_numbers.n),
                "e": _jwk_int(public_numbers.e),
            }
        ]
    }


def test_oauth_bearer_verifier_accepts_jwks_signed_rs256_token() -> None:
    """OAuth verifier should validate issuer, audience, expiry, and scopes."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    async def jwks_transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_jwks(private_key))

    now = datetime.now(UTC)
    token = _signed_jwt(
        private_key,
        {
            "iss": "https://auth.example.com",
            "aud": "https://mcp.example.com/mcp",
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "nbf": int((now - timedelta(minutes=1)).timestamp()),
            "scope": "alexandria:mcp alexandria:read",
        },
    )
    verifier = OAuthBearerTokenVerifier(
        OAuthBearerVerifierConfig(
            issuer="https://auth.example.com",
            audience="https://mcp.example.com/mcp",
            jwks_url="https://auth.example.com/.well-known/jwks.json",
            required_scopes=("alexandria:mcp",),
        ),
        transport=httpx.MockTransport(jwks_transport),
    )

    async def verify_token() -> str:
        claims = await verifier.verify(token)
        return claims.iss

    assert anyio.run(verify_token) == "https://auth.example.com"


def test_mcp_oauth_mode_challenges_missing_bearer_token() -> None:
    """OAuth MCP mode should use standard Bearer challenge, not custom headers."""
    scope = {
        "type": "http",
        "scheme": "https",
        "headers": [(b"host", b"mcp.example.com")],
    }
    gate = McpHttpAuthGate(McpAuthMode.OAUTH2)

    result = anyio.run(gate.authorize, scope)

    assert result.allowed is False
    assert result.status_code == 401
    assert result.detail == "OAuth bearer token required"
    assert result.headers["WWW-Authenticate"].startswith("Bearer ")
    assert (
        'resource_metadata="https://mcp.example.com/.well-known'
        in result.headers["WWW-Authenticate"]
    )


def test_mcp_protected_resource_metadata_uses_injected_oauth_config() -> None:
    """Protected-resource metadata should advertise configured OAuth servers."""
    request = Request(
        {
            "type": "http",
            "scheme": "https",
            "server": ("mcp.example.com", 443),
            "path": "/.well-known/oauth-protected-resource",
            "headers": [(b"host", b"mcp.example.com")],
        }
    )
    config = AppConfig(
        _env_file=None,
        mcp_auth_mode="oauth2",
        mcp_oauth_issuer="https://auth.example.com",
        mcp_oauth_audience="https://mcp.example.com/mcp",
        mcp_oauth_jwks_url="https://auth.example.com/.well-known/jwks.json",
        mcp_oauth_resource="https://mcp.example.com/mcp",
    )

    assert protected_resource_metadata(request, config) == {
        "resource": "https://mcp.example.com/mcp",
        "authorization_servers": ["https://auth.example.com"],
        "scopes_supported": ["alexandria:mcp"],
        "bearer_methods_supported": ["header"],
        "resource_documentation": "heterarchy-alexandria MCP server for librarian tools.",
    }
