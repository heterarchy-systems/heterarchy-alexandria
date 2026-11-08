"""Pydantic schemas for validating OAuth JWT/JWKS payloads."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

from app.mcp_server.type_validate.oauth.mcp_auth_enums import JwtAlgorithm
from app.shared.schemas.common_schemas import StrictSchemaModel


class JwtHeaderPayload(StrictSchemaModel):
    """Validated JWT JOSE header fields used by the MCP verifier."""

    alg: Annotated[JwtAlgorithm, Field(description="Alg for this JWT header payload.")]
    kid: Annotated[str, Field(description="Kid for this JWT header payload.")]


class JwtClaimsPayload(StrictSchemaModel):
    """Validated JWT claim fields required by the MCP resource server."""

    iss: Annotated[str, Field(description="Iss for this JWT claims payload.")]
    aud: Annotated[
        str | tuple[str, ...], Field(description="Aud for this JWT claims payload.")
    ]
    exp: Annotated[int, Field(description="Exp for this JWT claims payload.")]
    nbf: Annotated[
        int | None, Field(description="Nbf for this JWT claims payload.")
    ] = None
    scope: Annotated[
        str | None, Field(description="Scope for this JWT claims payload.")
    ] = None
    scp: Annotated[
        tuple[str, ...] | None, Field(description="Scp for this JWT claims payload.")
    ] = None


class RsaJsonWebKeyPayload(StrictSchemaModel):
    """Validated RSA JWK used to verify RS256 bearer tokens."""

    kty: Annotated[
        str,
        StringConstraints(strict=True, pattern="^RSA$"),
        Field(description="Kty for this rsa JSON web key payload."),
    ]
    kid: Annotated[str, Field(description="Kid for this rsa JSON web key payload.")]
    n: Annotated[str, Field(description="N for this rsa JSON web key payload.")]
    e: Annotated[str, Field(description="E for this rsa JSON web key payload.")]
    alg: Annotated[
        JwtAlgorithm | None, Field(description="Alg for this rsa JSON web key payload.")
    ] = None
    use: Annotated[
        str | None, Field(description="Use for this rsa JSON web key payload.")
    ] = None


class JsonWebKeySetPayload(StrictSchemaModel):
    """Validated JWKS response."""

    keys: Annotated[
        tuple[RsaJsonWebKeyPayload, ...],
        Field(description="Keys for this JSON web key set payload."),
    ]
