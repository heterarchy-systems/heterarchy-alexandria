"""Shared OpenAI/Codex execution support for librarian provider adapters."""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from app.connections.domain.event_enum.provider_enums import ProviderSecretKey
from app.connections.domain.repositories.librarian_repository import (
    IProviderSecretRepository,
)
from app.connections.infrastructure.librarians.openai_adapter import OpenAIClientConfig
from app.shared.serialization.orjson_codec import loads_json
from app.shared.types.extra_types import JSONValue
from app.shared.types.types_convert_utils import now_utc, optional_iso_utc_datetime
from openai import OpenAI
from openai.types.responses import ResponseTextDeltaEvent, WebSearchToolParam

CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
CODEX_USER_AGENT = "codex_cli_rs/0.0.0 (heterarchy-alexandria)"
CODEX_ORIGINATOR = "codex_cli_rs"


@dataclass(frozen=True, slots=True)
class OpenAIResponseSummaryFetcher:
    """Fetch response summaries through blocking OpenAI SDK calls.

    Args:
        strip_text_response: Whether non-streaming response text should be
            stripped before returning it to the caller.
    """

    strip_text_response: bool

    def fetch_openai_summary(
        self,
        client: OpenAI,
        model: str,
        prompt: str,
        instructions: str,
        *,
        enable_web_search: bool = False,
    ) -> str:
        """Fetch a non-streaming OpenAI Responses API summary.

        Args:
            client: OpenAI SDK client.
            model: Model name used for the response request.
            prompt: User prompt text.
            instructions: System/developer instructions passed to the model.

        Returns:
            Provider response text.
        """
        if enable_web_search:
            response = client.responses.create(
                model=model,
                input=prompt,
                instructions=instructions,
                tools=[
                    WebSearchToolParam(
                        type="web_search",
                        search_context_size="medium",
                    )
                ],
            )
        else:
            response = client.responses.create(
                model=model,
                input=prompt,
                instructions=instructions,
            )
        text = response.output_text
        if self.strip_text_response:
            return text.strip()
        return text

    def fetch_codex_stream_summary(
        self,
        client: OpenAI,
        model: str,
        prompt: str,
        instructions: str,
    ) -> str:
        """Fetch a streaming Codex summary and join text-delta events.

        Args:
            client: OpenAI-compatible Codex SDK client.
            model: Model name used for the response request.
            prompt: User prompt text.
            instructions: System/developer instructions passed to the model.

        Returns:
            Joined streamed text deltas.
        """
        stream = client.responses.create(
            model=model,
            input=[{"role": "user", "content": prompt}],
            instructions=instructions,
            store=False,
            stream=True,
        )
        text_parts = [
            event.delta for event in stream if isinstance(event, ResponseTextDeltaEvent)
        ]
        return "".join(text_parts).strip()


@dataclass(frozen=True, slots=True)
class OpenAICodexClientConfigBuilder:
    """Build Codex OAuth OpenAI SDK client config from provider secrets.

    Args:
        secret_repo: Provider secret resolver boundary.
        now_provider: Clock boundary used for access-token expiry checks.
    """

    secret_repo: IProviderSecretRepository
    now_provider: Callable[[], datetime] = now_utc

    async def build(
        self,
        *,
        provider_id: str,
        timeout: float | None = None,
    ) -> OpenAIClientConfig | None:
        """Build Codex client config when OAuth access-token material is usable.

        Args:
            provider_id: Provider identifier whose OAuth secrets are resolved.
            timeout: Optional SDK request timeout in seconds.

        Returns:
            OpenAI client config, or ``None`` when credentials are missing/stale.
        """
        access_token = await self.secret_repo.resolve(
            provider_id,
            ProviderSecretKey.OAUTH_ACCESS_TOKEN.value,
        )
        if not access_token:
            return None
        expires_at_value = await self.secret_repo.resolve(
            provider_id,
            ProviderSecretKey.OAUTH_EXPIRES_AT.value,
        )
        expires_at = optional_iso_utc_datetime(expires_at_value)
        if expires_at is not None and expires_at <= self.now_provider():
            return None
        client_config = OpenAIClientConfig(
            api_key=access_token,
            base_url=CODEX_BASE_URL,
            default_headers=OpenAICodexHeaderBuilder(access_token).headers(),
            timeout=timeout,
        )
        return client_config


@dataclass(frozen=True, slots=True)
class OpenAICodexHeaderBuilder:
    """Build Codex OAuth headers without exposing credential material.

    Args:
        access_token: OAuth access token used only for header derivation.
    """

    access_token: str

    def headers(self) -> dict[str, str]:
        """Build OpenAI-compatible Codex request headers.

        Returns:
            Header dictionary including account id when present in the token.
        """
        headers = {
            "User-Agent": CODEX_USER_AGENT,
            "originator": CODEX_ORIGINATOR,
        }
        account_id = self._chatgpt_account_id()
        if account_id is not None:
            headers["ChatGPT-Account-ID"] = account_id
        return headers

    def _chatgpt_account_id(self) -> str | None:
        parts = self.access_token.split(".")
        if len(parts) < 2:
            return None
        payload = self._decode_jwt_payload(parts[1])
        if payload is None:
            return None
        auth_claim = payload.get("https://api.openai.com/auth")
        if not isinstance(auth_claim, dict):
            return None
        account_id = auth_claim.get("chatgpt_account_id")
        if not isinstance(account_id, str):
            return None
        stripped = account_id.strip()
        if not stripped:
            return None
        return stripped

    def _decode_jwt_payload(self, payload: str) -> dict[str, JSONValue] | None:
        try:
            padded = payload + "=" * (-len(payload) % 4)
            raw_payload = base64.urlsafe_b64decode(padded.encode())
            decoded = loads_json(raw_payload)
        except ValueError:
            return None
        if not isinstance(decoded, dict):
            return None
        return cast(dict[str, JSONValue], decoded)


def string_config_value(value: JSONValue | None) -> str | None:
    """Return a non-empty string config value.

    Args:
        value: JSON config value from a provider row.

    Returns:
        Trimmed string when non-empty, otherwise ``None``.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def positive_float_config_value(value: JSONValue | None) -> float | None:
    """Return a positive numeric config value as float.

    Args:
        value: JSON config value from a provider row.

    Returns:
        Positive float, otherwise ``None``.
    """
    if isinstance(value, bool):
        return None
    if not isinstance(value, int | float):
        return None
    converted = float(value)
    if converted <= 0:
        return None
    return converted
