"""OAuth Bearer JWT verification for the ChatGPT-facing MCP endpoint."""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import ValidationError

from app.mcp_server.type_validate.oauth.oauth_jwt_schemas import (
    JsonWebKeySetPayload,
    JwtClaimsPayload,
    JwtHeaderPayload,
    RsaJsonWebKeyPayload,
)


class OAuthBearerTokenError(Exception):
    """Raised when an MCP OAuth bearer token is missing, invalid, or insufficient."""


@dataclass(frozen=True)
class OAuthBearerVerifierConfig:
    """Configuration needed to verify MCP OAuth Bearer JWTs."""

    issuer: str
    audience: str
    jwks_url: str
    required_scopes: tuple[str, ...]


class OAuthBearerTokenVerifier:
    """Verify RS256 OAuth Bearer JWTs against a configured JWKS endpoint."""

    def __init__(
        self,
        config: OAuthBearerVerifierConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Initialize OAuthBearerTokenVerifier state and dependencies.

        Args:
            config: Typed configuration used by this operation.
            transport: Transport used by this operation.
        """
        self._config = config
        self._transport = transport
        self._jwks: JsonWebKeySetPayload | None = None

    async def verify(self, token: str) -> JwtClaimsPayload:
        """Verify a bearer token and return validated claims.

        Args:
            token: JWT bearer token from the Authorization header.

        Returns:
            Validated JWT claims.

        Raises:
            OAuthBearerTokenError: If the token cannot be trusted.
        """
        header, claims, signing_input, signature = _decode_unsigned_token(token)
        key = self._public_key(header, await self._read_jwks())
        try:
            key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        except InvalidSignature as exc:
            raise OAuthBearerTokenError("Bearer token signature is invalid") from exc
        self._validate_claims(claims)
        return claims

    async def _read_jwks(self) -> JsonWebKeySetPayload:
        """Read jwks.

        Returns:
            Loaded jwks.
        """
        if self._jwks is not None:
            return self._jwks
        async with httpx.AsyncClient(transport=self._transport, timeout=10.0) as client:
            response = await client.get(self._config.jwks_url)
            response.raise_for_status()
        try:
            payload = JsonWebKeySetPayload.model_validate_json(response.content)
        except ValidationError as exc:
            raise OAuthBearerTokenError("JWKS payload is invalid") from exc
        self._jwks = payload
        return payload

    def _public_key(
        self,
        header: JwtHeaderPayload,
        jwks: JsonWebKeySetPayload,
    ) -> rsa.RSAPublicKey:
        """Execute public key.

        Args:
            header: Header used by this operation.
            jwks: Jwks used by this operation.

        Returns:
            rsa.RSAPublicKey result produced by public key.
        """
        for key in jwks.keys:
            if key.kid == header.kid:
                return _rsa_public_key(key)
        raise OAuthBearerTokenError("Bearer token key id is unknown")

    def _validate_claims(self, claims: JwtClaimsPayload) -> None:
        """Validate claims.

        Args:
            claims: Claims used by this operation.
        """
        now = int(datetime.now(UTC).timestamp())
        if claims.iss != self._config.issuer:
            raise OAuthBearerTokenError("Bearer token issuer is invalid")
        if not _audience_matches(claims.aud, self._config.audience):
            raise OAuthBearerTokenError("Bearer token audience is invalid")
        if claims.exp <= now:
            raise OAuthBearerTokenError("Bearer token is expired")
        if claims.nbf is not None and claims.nbf > now:
            raise OAuthBearerTokenError("Bearer token is not active yet")
        missing = set(self._config.required_scopes) - set(_claim_scopes(claims))
        if missing:
            raise OAuthBearerTokenError("Bearer token scope is insufficient")


def _decode_unsigned_token(
    token: str,
) -> tuple[JwtHeaderPayload, JwtClaimsPayload, bytes, bytes]:
    """Decode unsigned token.

    Args:
        token: Token used by this operation.

    Returns:
        Decoded unsigned token.
    """
    segments = token.split(".")
    if len(segments) != 3:
        raise OAuthBearerTokenError("Bearer token is not a JWT")
    header_segment, claim_segment, signature_segment = segments
    signing_input = f"{header_segment}.{claim_segment}".encode("ascii")
    try:
        header = JwtHeaderPayload.model_validate_json(_decode_base64url(header_segment))
        claims = JwtClaimsPayload.model_validate_json(_decode_base64url(claim_segment))
        signature = _decode_base64url(signature_segment)
    except (UnicodeEncodeError, ValidationError, ValueError) as exc:
        raise OAuthBearerTokenError("Bearer token payload is invalid") from exc
    return header, claims, signing_input, signature


def _decode_base64url(value: str) -> bytes:
    """Decode base64url.

    Args:
        value: Value being processed.

    Returns:
        Decoded base64url.
    """
    padding_length = (-len(value)) % 4
    padded = value + ("=" * padding_length)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _rsa_public_key(key: RsaJsonWebKeyPayload) -> rsa.RSAPublicKey:
    """Execute rsa public key.

    Args:
        key: Key used by this operation.

    Returns:
        rsa.RSAPublicKey result produced by rsa public key.
    """
    public_numbers = rsa.RSAPublicNumbers(
        e=int.from_bytes(_decode_base64url(key.e), "big"),
        n=int.from_bytes(_decode_base64url(key.n), "big"),
    )
    public_key = public_numbers.public_key()
    return cast(rsa.RSAPublicKey, public_key)


def _audience_matches(aud: str | tuple[str, ...], expected: str) -> bool:
    """Execute audience matches.

    Args:
        aud: Aud used by this operation.
        expected: Expected used by this operation.

    Returns:
        Whether audience matches.
    """
    if isinstance(aud, str):
        return aud == expected
    return expected in aud


def _claim_scopes(claims: JwtClaimsPayload) -> Sequence[str]:
    """Execute claim scopes.

    Args:
        claims: Claims used by this operation.

    Returns:
        Sequence[str] result produced by claim scopes.
    """
    if claims.scp is not None:
        return claims.scp
    if claims.scope is not None:
        return tuple(scope for scope in claims.scope.split(" ") if scope)
    return ()
