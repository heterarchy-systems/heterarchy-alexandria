"""Pruning contracts for Context Vault save-before-review routes."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from app.main import app
from fastapi.testclient import TestClient
from tests.shared.provider_overrides import override_library_provider


class FailingContextReviewService:
    """Fail if a pruned context review/manual-save route reaches the service."""

    def __getattr__(self, name: str) -> Callable[..., object]:
        """Return a callable that fails on accidental service access."""

        def fail(*_args: object, **_kwargs: object) -> object:
            raise AssertionError(f"pruned context service method called: {name}")

        return fail


_CONTEXT_PAYLOAD = {
    "kind": "HANDOFF",
    "title": "Manual review context",
    "summary": "This path should not support pre-save review.",
    "content": "# Manual review context\n\n## Summary\nReview-before-save is pruned.",
    "project": "heterarchy-alexandria",
    "source_agent": "Hermes",
}


@pytest.mark.parametrize("path", ["/memory/contexts/lint", "/memory/contexts"])
def test_context_lint_and_manual_save_routes_are_not_exposed(path: str) -> None:
    """Capture Review linting and generic manual context save should be absent."""
    with (
        override_library_provider("context_service", FailingContextReviewService()),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.post(path, json=_CONTEXT_PAYLOAD)

    assert response.status_code in {404, 405}
