"""OpenAI librarian provider SDK adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from openai import OpenAI

from app.connections.domain.contracts.librarian_client_contracts import (
    ApiKeyCredential,
    ProviderClientTestResult,
)
from app.connections.domain.event_enum.provider_enums import ProviderType
from app.shared.exceptions.connections_exceptions import (
    ConnectionsProviderUnsupportedError,
)
from app.shared.types.extra_types import JSONObject


@dataclass(slots=True)
class OpenAIClientConfig:
    """Constructor config for the official OpenAI SDK client."""

    api_key: str
    base_url: str | None = None
    default_headers: Mapping[str, str] | None = None
    timeout: float | None = None

    def __post_init__(self) -> None:
        """Freeze optional SDK headers after config construction."""
        if self.default_headers is not None:
            self.default_headers = MappingProxyType(dict(self.default_headers))


OpenAIClientBuilder = Callable[[OpenAIClientConfig], OpenAI]


@dataclass(frozen=True, slots=True)
class OpenAIStyleSDKAdapter:
    """Adapter for the official OpenAI SDK client."""

    client: OpenAI
    provider_type: ProviderType
    dry_run: bool = True

    async def test_connection(self, test_query: str) -> ProviderClientTestResult:
        """Perform a deterministic default connection test.

        Args:
            test_query: Query text submitted by callers. Default dry-run mode does
                not send it to external services.

        Returns:
            Provider test result.
        """
        _ = test_query
        if self.dry_run:
            result = ProviderClientTestResult(
                provider_id="",
                ok=True,
                message=f"{self.provider_type.value} SDK client dry-run accepted query",
            )
            return result
        result = ProviderClientTestResult(
            provider_id="",
            ok=False,
            message="live SDK connection tests are not enabled",
        )
        return result


def build_openai_client_config(
    provider_type: ProviderType,
    config: JSONObject,
    credential: ApiKeyCredential,
) -> OpenAIClientConfig:
    """Build constructor config for the official OpenAI SDK client.

    Args:
        provider_type: Provider type requested by the caller.
        config: Provider config payload. OpenAI currently requires no config keys.
        credential: Redacted API-key credential.

    Returns:
        OpenAIClientConfig: Official OpenAI SDK constructor config.
    """
    _ = config
    if provider_type is not ProviderType.OPENAI:
        raise ConnectionsProviderUnsupportedError(
            f"provider type {provider_type.value} is unsupported for OpenAI SDK clients"
        )
    client_config = OpenAIClientConfig(api_key=credential.value)
    return client_config


def build_openai_client(config: OpenAIClientConfig) -> OpenAI:
    """Construct the official OpenAI SDK client.

    Args:
        config: Official OpenAI SDK constructor config.

    Returns:
        OpenAI: Official OpenAI SDK client.
    """
    client = OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        default_headers=(
            None if config.default_headers is None else dict(config.default_headers)
        ),
        timeout=config.timeout,
    )
    return client
