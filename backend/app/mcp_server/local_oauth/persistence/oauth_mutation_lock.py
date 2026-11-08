"""Transaction-bound serialization for the local OAuth state aggregate."""

from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.infrastructure.postgres_advisory_lock import postgres_advisory_lock_key

_OAUTH_MUTATION_KEY = postgres_advisory_lock_key(
    namespace="heterarchy-alexandria:local-mcp-oauth:mutations"
)


async def lock_oauth_mutation(session: AsyncSession) -> None:
    """Serialize a mutation before it reads state in its owned transaction.

    Args:
        session: Fresh session inside the repository's transaction context.

    Raises:
        RuntimeError: Transaction isolation cannot provide post-lock fresh reads.

    The transaction context releases this PostgreSQL lock at commit or rollback.
    Every OAuth mutation acquires this aggregate lock before taking row locks.
    """
    isolation: object = await session.scalar(text("SHOW transaction_isolation"))
    if isolation != "read committed":
        raise RuntimeError(
            "Local MCP OAuth mutations require READ COMMITTED transactions"
        )
    await session.execute(select(func.pg_advisory_xact_lock(_OAUTH_MUTATION_KEY)))
