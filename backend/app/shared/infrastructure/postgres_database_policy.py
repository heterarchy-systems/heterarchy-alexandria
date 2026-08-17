"""PostgreSQL connection-pool and session timeout policies."""

from __future__ import annotations

POSTGRES_POOL_SIZE = 10
POSTGRES_MAX_OVERFLOW = 10
POSTGRES_POOL_TIMEOUT_SECONDS = 30.0
POSTGRES_POOL_RECYCLE_SECONDS = 30 * 60
POSTGRES_COMMAND_TIMEOUT_SECONDS = 30.0
POSTGRES_STATEMENT_TIMEOUT_MS = 30_000
POSTGRES_LOCK_TIMEOUT_MS = 5_000
POSTGRES_IDLE_TRANSACTION_TIMEOUT_MS = 60_000


def postgres_connect_args() -> dict[str, float | dict[str, str]]:
    """Build asyncpg connection arguments for bounded database work.

    Returns:
        Driver arguments with command and server-side timeout policies.
    """
    return {
        "command_timeout": POSTGRES_COMMAND_TIMEOUT_SECONDS,
        "server_settings": {
            "application_name": "heterarchy-alexandria",
            "timezone": "UTC",
            "statement_timeout": str(POSTGRES_STATEMENT_TIMEOUT_MS),
            "lock_timeout": str(POSTGRES_LOCK_TIMEOUT_MS),
            "idle_in_transaction_session_timeout": str(
                POSTGRES_IDLE_TRANSACTION_TIMEOUT_MS
            ),
        },
    }
