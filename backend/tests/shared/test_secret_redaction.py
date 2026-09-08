"""Persistence-boundary secret redaction behavior tests."""

from __future__ import annotations

import pytest

from app.shared.utils.secret_redaction import (
    BLOCKED_SECRET_PLACEHOLDER,
    redact_secret_text,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.example.com/news/article/20260729/123456",
        "https://example.com/news/" + ("public-article-path-" * 8),
        "https://example.com/%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90",
        "https://example.com/articles/123e4567-e89b-12d3-a456-426614174000",
        "https://example.com/article?id=12345&language=ko",
        "https://example.com/article?tracking="
        + "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    ],
)
def test_redact_secret_text_preserves_public_urls(url: str) -> None:
    result = redact_secret_text(f"Source: {url}")

    assert result.redacted_content == f"Source: {url}"
    assert result.redaction_count == 0
    assert result.warnings == ()


@pytest.mark.parametrize(
    "credential_name",
    [
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "secret",
        "client_secret",
        "signature",
        "sig",
        "authorization",
        "auth",
        "password",
        "passwd",
        "session",
        "session_token",
    ],
)
def test_redact_secret_text_redacts_only_credential_query_values(
    credential_name: str,
) -> None:
    url = (
        "https://example.com/article?"
        f"id=12345&{credential_name}=SECRET-VALUE&language=ko#sources"
    )

    result = redact_secret_text(url)

    assert result.redacted_content == (
        "https://example.com/article?"
        f"id=12345&{credential_name}=<REDACTED>&language=ko#sources"
    )
    assert result.redaction_count == 1
    assert result.warnings == ("potential secret-like content was redacted",)


def test_redact_secret_text_preserves_query_order_fragment_and_key_spelling() -> None:
    url = (
        "https://example.com/article?"
        "first=1&Access_Token=SECRET&middle=2&api_key=ANOTHER-SECRET&last=3"
        "#evidence-fragment"
    )

    result = redact_secret_text(url)

    assert result.redacted_content == (
        "https://example.com/article?"
        "first=1&Access_Token=<REDACTED>&middle=2&api_key=<REDACTED>&last=3"
        "#evidence-fragment"
    )
    assert result.redaction_count == 2


def test_redact_secret_text_preserves_markdown_around_credential_url() -> None:
    content = (
        "See [source](https://example.com/article?id=1&access_token=SECRET-VALUE)."
    )

    result = redact_secret_text(content)

    assert result.redacted_content == (
        "See [source](https://example.com/article?id=1&access_token=<REDACTED>)."
    )
    assert result.redaction_count == 1


def test_redact_secret_text_keeps_generic_long_token_redaction_outside_urls() -> None:
    token = "a" * 64

    result = redact_secret_text(f"Stored token material: {token}")

    assert result.redacted_content == "Stored token material: <REDACTED_LONG_VALUE>"
    assert result.redaction_count == 1


def test_redact_secret_text_preserves_obsidian_full_path_wikilink() -> None:
    content = (
        "routes_to -> "
        "[[Prompts/System/Scheduler/Execution/Crypto/Bitcoin Morning Read v3|"
        "Bitcoin Morning Read v3]]"
    )

    result = redact_secret_text(content)

    assert result.redacted_content == content
    assert result.redaction_count == 0
    assert result.warnings == ()


def test_redact_secret_text_redacts_long_token_inside_wikilink_path_segment() -> None:
    token = "a" * 64
    content = f"[[Contexts/Projects/{token}/Note|label]]"

    result = redact_secret_text(content)

    assert result.redacted_content == (
        "[[Contexts/Projects/<REDACTED_LONG_VALUE>/Note|label]]"
    )
    assert result.redaction_count == 1
    assert result.warnings == ("potential secret-like content was redacted",)


def test_redact_secret_text_redacts_authorization_and_bearer_tokens() -> None:
    result = redact_secret_text(
        "Authorization: Bearer short-but-sensitive-token\n"
        "Fallback Bearer another-short-secret"
    )

    assert result.redacted_content == (
        "Authorization: Bearer <REDACTED>\nFallback Bearer <REDACTED>"
    )
    assert result.redaction_count == 2


def test_redact_secret_text_redacts_basic_authorization_credentials() -> None:
    result = redact_secret_text("Authorization: Basic dXNlcjpwYXNzd29yZA==")

    assert result.redacted_content == "Authorization: Basic <REDACTED>"
    assert result.redaction_count == 1


def test_redact_secret_text_redacts_credential_values_in_url_fragment() -> None:
    url = (
        "https://example.com/oauth/callback?"
        "state=public#access_token=SECRET&token_type=bearer&section=result"
    )

    result = redact_secret_text(url)

    assert result.redacted_content == (
        "https://example.com/oauth/callback?"
        "state=public#access_token=<REDACTED>&token_type=bearer&section=result"
    )
    assert result.redaction_count == 1


def test_redact_secret_text_still_blocks_private_keys() -> None:
    result = redact_secret_text(
        "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"
    )

    assert result.blocked is True
    assert result.redacted_content == BLOCKED_SECRET_PLACEHOLDER
    assert result.redaction_count == 1
    assert result.warnings == ("high-risk secret content cannot be saved raw",)


def test_declared_sha256_provenance_retains_the_complete_digest() -> None:
    digest = "a1b2c3d4" * 8
    result = redact_secret_text(f"policy-version:5:sha256:{digest}")
    assert result.redacted_content == f"policy-version:5:sha256:{digest}"
    assert result.redaction_count == 0


@pytest.mark.parametrize(
    "field", ["api_key", "token", "password", "password_hash", "hashed_password"]
)
def test_hash_syntax_does_not_exempt_credential_assignments(field: str) -> None:
    digest = "a1b2c3d4" * 8
    result = redact_secret_text(f"{field}=sha256:{digest}")
    assert digest not in result.redacted_content
    assert result.redaction_count > 0


@pytest.mark.parametrize("value", ["a1b2c3d4" * 8, "sha256:" + "g" * 64])
def test_opaque_or_malformed_hash_like_values_still_redact(value: str) -> None:
    result = redact_secret_text(value)
    assert result.redaction_count == 1
