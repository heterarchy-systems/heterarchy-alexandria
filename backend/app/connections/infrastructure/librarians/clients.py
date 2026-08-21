"""SDK-backed API-key client foundation for librarian providers."""

from __future__ import annotations

from dataclasses import dataclass

from app.connections.domain.contracts.librarian_client_contracts import (
    ApiKeyCredential,
    LibrarianProviderClientFactory,
    ProviderClientTestResult,
)
from app.connections.domain.entities.read_models import LibrarianProvider
from app.connections.domain.event_enum.provider_enums import (
    AuthType,
    ProviderSecretKey,
    ProviderType,
)
from app.connections.domain.repositories.librarian_repository import (
    IProviderSecretRepository as SecretResolver,
)
from app.connections.infrastructure.librarians.openai_adapter import (
    OpenAIClientBuilder,
    OpenAIStyleSDKAdapter,
    build_openai_client,
    build_openai_client_config,
)
from app.connections.infrastructure.librarians.provider_types import (
    SUPPORTED_SDK_PROVIDER_TYPES,
    parse_auth_type,
    parse_provider_type,
)
from app.shared.exceptions.connections_exceptions import (
    ConnectionsProviderUnsupportedError,
)
from app.shared.types.extra_types import JSONObject
from app.shared.types.types_convert_utils import now_utc, optional_iso_utc_datetime


@dataclass(frozen=True, slots=True)
class LibrarianClientFactory(LibrarianProviderClientFactory):
    """Factory for API-key SDK-backed librarian provider adapters.

    Args:
        openai_client_builder: Optional injected OpenAI SDK constructor.
        dry_run: When true, adapters instantiate SDK clients but do not perform
            network requests. This keeps default tests deterministic.
    """

    openai_client_builder: OpenAIClientBuilder = build_openai_client
    dry_run: bool = True

    async def test_connection(
        self,
        provider: LibrarianProvider,
        secret_resolver: SecretResolver,
        test_query: str,
    ) -> ProviderClientTestResult:
        """Build the correct SDK adapter and run a deterministic connection test.

        Args:
            provider: Librarian provider configuration.
            secret_resolver: Secret resolver boundary for API keys.
            test_query: Caller-provided test query.

        Returns:
            Public test result without credential material.
        """
        if not provider.enabled:
            result = ProviderClientTestResult(
                provider_id=provider.id,
                ok=False,
                message="provider disabled",
            )
            return result

        auth_type = parse_auth_type(provider.auth_type)
        provider_type = parse_provider_type(provider.provider_type)
        if provider_type is None:
            result = ProviderClientTestResult(
                provider_id=provider.id,
                ok=False,
                message=(
                    f"provider type {provider.provider_type} is unsupported for "
                    "librarian SDK clients"
                ),
            )
            return result

        if provider_type is ProviderType.OPENAI_CODEX:
            result = await self._test_openai_codex_oauth(
                provider=provider,
                auth_type=auth_type,
                secret_resolver=secret_resolver,
            )
            return result

        if auth_type is not AuthType.API_KEY:
            result = ProviderClientTestResult(
                provider_id=provider.id,
                ok=False,
                message=(
                    f"auth type {provider.auth_type} is unsupported for "
                    "API-key SDK clients"
                ),
            )
            return result

        if provider_type not in SUPPORTED_SDK_PROVIDER_TYPES:
            result = ProviderClientTestResult(
                provider_id=provider.id,
                ok=False,
                message=(
                    f"provider type {provider.provider_type} is unsupported for "
                    "librarian SDK clients"
                ),
            )
            return result

        api_key = await secret_resolver.resolve(
            provider.id,
            ProviderSecretKey.API_KEY.value,
        )
        if not api_key:
            result = ProviderClientTestResult(
                provider_id=provider.id,
                ok=False,
                message="api_key missing",
            )
            return result
        credential = ApiKeyCredential(api_key)
        try:
            adapter = self._build_adapter(provider_type, provider.config, credential)
        except ConnectionsProviderUnsupportedError as exc:
            result = ProviderClientTestResult(
                provider_id=provider.id,
                ok=False,
                message=str(exc),
            )
            return result
        adapter_result = await adapter.test_connection(test_query)
        result = ProviderClientTestResult(
            provider_id=provider.id,
            ok=adapter_result.ok,
            message=adapter_result.message,
        )
        return result

    async def _test_openai_codex_oauth(
        self,
        provider: LibrarianProvider,
        auth_type: AuthType,
        secret_resolver: SecretResolver,
    ) -> ProviderClientTestResult:
        if auth_type is not AuthType.OAUTH:
            result = ProviderClientTestResult(
                provider_id=provider.id,
                ok=False,
                message="provider type OPENAI_CODEX requires OAUTH auth",
            )
            return result

        access_token = await secret_resolver.resolve(
            provider.id,
            ProviderSecretKey.OAUTH_ACCESS_TOKEN.value,
        )
        refresh_token = await secret_resolver.resolve(
            provider.id,
            ProviderSecretKey.OAUTH_REFRESH_TOKEN.value,
        )
        expires_at_value = await secret_resolver.resolve(
            provider.id,
            ProviderSecretKey.OAUTH_EXPIRES_AT.value,
        )
        if access_token is None:
            result = ProviderClientTestResult(
                provider_id=provider.id,
                ok=False,
                message=(
                    "oauth access token missing"
                    if refresh_token
                    else "oauth credentials missing"
                ),
            )
            return result
        expires_at = optional_iso_utc_datetime(expires_at_value)
        if expires_at is None:
            return ProviderClientTestResult(
                provider_id=provider.id,
                ok=False,
                message="oauth token expiry missing or invalid",
            )
        if expires_at <= now_utc():
            return ProviderClientTestResult(
                provider_id=provider.id,
                ok=False,
                message="oauth access token expired",
            )

        result = ProviderClientTestResult(
            provider_id=provider.id,
            ok=True,
            message="OPENAI_CODEX OAuth credentials available",
        )
        return result

    def _build_adapter(
        self,
        provider_type: ProviderType,
        config: JSONObject,
        credential: ApiKeyCredential,
    ) -> OpenAIStyleSDKAdapter:
        """Build an SDK adapter for an OpenAI provider type.

        Args:
            provider_type: Supported OpenAI provider type.
            config: Provider configuration payload.
            credential: Redacted API-key credential.

        Returns:
            OpenAIStyleSDKAdapter: OpenAI SDK adapter.
        """
        if provider_type is not ProviderType.OPENAI:
            raise ConnectionsProviderUnsupportedError(
                f"provider type {provider_type.value} is unsupported for librarian SDK clients"
            )
        client_config = build_openai_client_config(provider_type, config, credential)
        adapter = OpenAIStyleSDKAdapter(
            client=self.openai_client_builder(client_config),
            provider_type=provider_type,
            dry_run=self.dry_run,
        )
        return adapter


__all__ = [
    "ApiKeyCredential",
    "LibrarianClientFactory",
    "LibrarianProviderClientFactory",
    "OpenAIStyleSDKAdapter",
    "ProviderClientTestResult",
    "SecretResolver",
]
