"""Authentication gate for the public MCP Streamable HTTP mount."""

from __future__ import annotations

from http import HTTPStatus

from starlette.types import Scope

from app.mcp_server.oauth_bearer_verifier import (
    OAuthBearerTokenError,
    OAuthBearerTokenVerifier,
)
from app.mcp_server.type_validate.oauth.auth_contracts import (
    MCP_OAUTH_PROTECTED_RESOURCE_PATH,
    McpHttpAuthResult,
)
from app.mcp_server.type_validate.oauth.mcp_auth_enums import (
    McpAuthMode,
    OAuthBearerErrorCode,
)


class McpHttpAuthGate:
    """Authorize public MCP HTTP requests with no-auth or OAuth2 Bearer mode."""

    def __init__(
        self,
        auth_mode: McpAuthMode,
        verifier: OAuthBearerTokenVerifier | None = None,
    ) -> None:
        """Initialize McpHttpAuthGate state and dependencies.

        Args:
            auth_mode: Auth mode used by this operation.
            verifier: Verifier used by this operation.
        """
        self._auth_mode = auth_mode
        self._verifier = verifier

    async def authorize(self, scope: Scope) -> McpHttpAuthResult:
        """Authorize one ASGI request before it reaches the MCP server.

        Args:
            scope: ASGI request scope.

        Returns:
            Authorization result.
        """
        if self._auth_mode is McpAuthMode.NONE or scope["type"] != "http":
            return McpHttpAuthResult(allowed=True)
        if self._verifier is None:
            return self._deny(scope, OAuthBearerErrorCode.INVALID_REQUEST)
        token = _bearer_token(scope)
        if token is None:
            return self._deny(scope, OAuthBearerErrorCode.INVALID_REQUEST)
        try:
            await self._verifier.verify(token)
        except OAuthBearerTokenError:
            return self._deny(scope, OAuthBearerErrorCode.INVALID_TOKEN)
        return McpHttpAuthResult(allowed=True)

    def _deny(
        self,
        scope: Scope,
        error_code: OAuthBearerErrorCode,
    ) -> McpHttpAuthResult:
        """Execute deny.

        Args:
            scope: Scope used by this operation.
            error_code: Error code used by this operation.

        Returns:
            McpHttpAuthResult result produced by deny.
        """
        return McpHttpAuthResult(
            allowed=False,
            status_code=HTTPStatus.UNAUTHORIZED,
            detail="OAuth bearer token required",
            headers={"WWW-Authenticate": _www_authenticate(scope, error_code)},
        )


def _bearer_token(scope: Scope) -> str | None:
    """Execute bearer token.

    Args:
        scope: Scope used by this operation.

    Returns:
        str | None result produced by bearer token.
    """
    headers = dict(scope.get("headers", []))
    raw_authorization = headers.get(b"authorization")
    if raw_authorization is None:
        return None
    try:
        authorization = raw_authorization.decode("utf-8")
    except UnicodeDecodeError:
        return None
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return None
    token = authorization[len(prefix) :].strip()
    return token or None


def _www_authenticate(scope: Scope, error_code: OAuthBearerErrorCode) -> str:
    """Execute www authenticate.

    Args:
        scope: Scope used by this operation.
        error_code: Error code used by this operation.

    Returns:
        str result produced by www authenticate.
    """
    metadata_url = f"{_request_origin(scope)}{MCP_OAUTH_PROTECTED_RESOURCE_PATH}"
    return (
        f'Bearer resource_metadata="{metadata_url}", '
        f'error="{error_code.value}", '
        'error_description="OAuth bearer token required"'
    )


def _request_origin(scope: Scope) -> str:
    """Execute request origin.

    Args:
        scope: Scope used by this operation.

    Returns:
        str result produced by request origin.
    """
    headers = dict(scope.get("headers", []))
    forwarded_proto = _header_text(headers, b"x-forwarded-proto")
    forwarded_host = _header_text(headers, b"x-forwarded-host")
    scheme = forwarded_proto or str(scope.get("scheme", "http"))
    host = forwarded_host or _header_text(headers, b"host") or "localhost"
    return f"{scheme}://{host}"


def _header_text(headers: dict[bytes, bytes], key: bytes) -> str | None:
    """Execute header text.

    Args:
        headers: Headers used by this operation.
        key: Key used by this operation.

    Returns:
        str | None result produced by header text.
    """
    value = headers.get(key)
    if value is None:
        return None
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return None
