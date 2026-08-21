"""Pydantic schemas for validating OAuth JWT/JWKS payloads."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

from app.mcp_server.type_validate.oauth.mcp_auth_enums import JwtAlgorithm
from app.shared.schemas.common_schemas import StrictSchemaModel, described_field


class JwtHeaderPayload(StrictSchemaModel):
    """Validated JWT JOSE header fields used by the MCP verifier."""

    alg: Annotated[JwtAlgorithm, described_field("Alg for this JWT header payload.")]
    kid: Annotated[str, described_field("Kid for this JWT header payload.")]


class JwtClaimsPayload(StrictSchemaModel):
    """Validated JWT claim fields required by the MCP resource server."""

    iss: Annotated[str, described_field("Iss for this JWT claims payload.")]
    aud: Annotated[
        str | tuple[str, ...], described_field("Aud for this JWT claims payload.")
    ]
    exp: Annotated[int, described_field("Exp for this JWT claims payload.")]
    nbf: Annotated[int | None, described_field("Nbf for this JWT claims payload.")] = (
        None
    )
    scope: Annotated[
        str | None, described_field("Scope for this JWT claims payload.")
    ] = None
    scp: Annotated[
        tuple[str, ...] | None, described_field("Scp for this JWT claims payload.")
    ] = None


class RsaJsonWebKeyPayload(StrictSchemaModel):
    """Validated RSA JWK used to verify RS256 bearer tokens."""

    kty: Annotated[
        str,
        StringConstraints(strict=True, pattern="^RSA$"),
        described_field("Kty for this rsa JSON web key payload."),
    ]
    kid: Annotated[str, described_field("Kid for this rsa JSON web key payload.")]
    n: Annotated[str, described_field("N for this rsa JSON web key payload.")]
    e: Annotated[str, described_field("E for this rsa JSON web key payload.")]
    alg: Annotated[
        JwtAlgorithm | None, described_field("Alg for this rsa JSON web key payload.")
    ] = None
    use: Annotated[
        str | None, described_field("Use for this rsa JSON web key payload.")
    ] = None


class JsonWebKeySetPayload(StrictSchemaModel):
    """Validated JWKS response."""

    keys: Annotated[
        tuple[RsaJsonWebKeyPayload, ...],
        described_field("Keys for this JSON web key set payload."),
    ]
