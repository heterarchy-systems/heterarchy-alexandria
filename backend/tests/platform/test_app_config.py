"""Required app configuration contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.platform.config.app_config import AppConfig


def test_app_config_requires_every_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing process settings must fail closed at the settings boundary."""
    monkeypatch.delenv("SERVICE_APP_NAME", raising=False)
    with pytest.raises(ValidationError):
        AppConfig(_env_file=None)
