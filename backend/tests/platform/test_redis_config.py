"""Redis configuration contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.platform.config.redis_config import RedisConfig
from tests.config_test_data import redis_config_values


def test_redis_config_requires_all_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis construction requires explicit values, including its optional URL."""
    monkeypatch.delenv("SERVICE_REDIS_MAX_CONNECTIONS", raising=False)
    with pytest.raises(ValidationError):
        RedisConfig(_env_file=None)


def test_redis_config_accepts_explicitly_disabled_url() -> None:
    """An explicit null URL keeps Redis disabled while retaining configured TTL."""
    config = RedisConfig(_env_file=None, **redis_config_values(url=None))

    assert config.url is None
    assert config.operational_readiness_ttl_seconds == 5


def test_redis_config_normalizes_blank_url_to_disabled() -> None:
    """Blank optional URL values should not create a partially enabled client."""
    config = RedisConfig(_env_file=None, **redis_config_values(url="   "))

    assert config.url is None


@pytest.mark.parametrize("ttl_seconds", [0, 31])
def test_redis_config_rejects_out_of_range_ttl(ttl_seconds: int) -> None:
    """Readiness caching must remain short lived and finite."""
    with pytest.raises(ValidationError):
        RedisConfig(
            _env_file=None,
            **redis_config_values(operational_readiness_ttl_seconds=ttl_seconds),
        )
