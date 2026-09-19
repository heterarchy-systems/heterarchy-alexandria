"""Behavior tests for the bounded Context change-log delta read path."""

from __future__ import annotations

import os
from base64 import urlsafe_b64encode
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from json import dumps
from typing import cast

import anyio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from tests.memory.context_seed import seed_context

from app.memory.domain.entities.context_change_log import ContextDeltaPage
from app.memory.domain.event_enum.context_enums import ContextChangeKind, ContextKind
from app.memory.domain.types.context_change_cursor import (
    CONTEXT_CHANGE_CURSOR_VERSION,
    CONTEXT_CHANGE_LOG_SCOPE,
    decode_context_change_cursor,
)
from app.memory.infrastructure.repositories.context_repository import (
    SqlAlchemyContextRepository,
)
from app.memory.infrastructure.repositories.contexts.records.context_change_log_writer import (
    context_change_content_hash,
    record_context_change,
)
from app.shared.exceptions.memory_context_exceptions import (
    ContextChangeCursorInvalidError,
    ContextChangeCursorResyncRequiredError,
)
from app.shared.infrastructure.database import Database


@asynccontextmanager
async def _postgres_session() -> AsyncIterator[AsyncSession]:
    """Yield one PostgreSQL session against the migration-faithful test database."""
    database = Database(database_url=os.environ["DATABASE_URL"], create_schema=True)
    await database.initialize()
    try:
        async with database.session() as session:
            yield session
    finally:
        await database.shutdown()


async def _repository(session: AsyncSession) -> SqlAlchemyContextRepository:
    """Create one repository facade for the session.

    Args:
        session: Active async database session.

    Returns:
        SQL-backed Context repository.
    """
    return SqlAlchemyContextRepository(session=session)


async def _full_delta_page(session: AsyncSession) -> ContextDeltaPage:
    """Read one fresh bounded delta page across the whole log.

    Args:
        session: Active async database session.

    Returns:
        Delta page for the whole log.
    """
    repository = await _repository(session)
    return await repository.context_delta(cursor_token=None, max_rows=64)


def _foreign_scope_token(
    scope: str, version: int = CONTEXT_CHANGE_CURSOR_VERSION
) -> str:
    """Encode a structurally valid cursor token with a foreign scope/version.

    Args:
        scope: Foreign scope string to embed.
        version: Foreign format version to embed.

    Returns:
        Encoded opaque token in the standard wire format.
    """
    payload = dumps({"v": version, "scope": scope, "last_sequence": 0})
    return urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def test_context_change_log_migration_owns_tables_and_checked_kinds() -> None:
    """Alembic migrations should own both change-log tables with pinned kinds."""

    async def scenario() -> tuple[set[str], set[str], list[str]]:
        engine = create_async_engine(os.environ["DATABASE_URL"])
        try:
            async with engine.connect() as connection:
                tables = (
                    (
                        await connection.execute(
                            text(
                                "SELECT tablename FROM pg_tables WHERE schemaname = "
                                "'public' AND tablename IN "
                                "('context_change_log', 'context_change_log_meta')"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                columns = (
                    (
                        await connection.execute(
                            text(
                                "SELECT table_name || '.' || column_name FROM "
                                "information_schema.columns WHERE table_schema = "
                                "'public' AND table_name IN ('context_change_log', "
                                "'context_change_log_meta')"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                constraints = (
                    (
                        await connection.execute(
                            text(
                                "SELECT conname FROM pg_constraint WHERE conname IN "
                                "('ck_context_change_log_change_kind', "
                                "'ck_context_change_log_meta_singleton', "
                                "'ck_context_change_log_meta_non_negative')"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                return set(tables), set(columns), list(constraints)
        finally:
            await engine.dispose()

    tables, columns, constraints = anyio.run(scenario)

    assert tables == {"context_change_log", "context_change_log_meta"}
    assert {
        "context_change_log.sequence",
        "context_change_log.context_id",
        "context_change_log.change_kind",
        "context_change_log.content_hash",
        "context_change_log.recorded_at",
        "context_change_log_meta.singleton_id",
        "context_change_log_meta.high_water_seq",
    } <= columns
    assert set(constraints) == {
        "ck_context_change_log_change_kind",
        "ck_context_change_log_meta_singleton",
        "ck_context_change_log_meta_non_negative",
    }


def test_context_delta_empty_log_returns_fresh_cursor_without_entries() -> None:
    """An empty log should return no entries and a usable fresh cursor."""

    async def scenario() -> tuple[bool, bool, int, bool]:
        async with _postgres_session() as session:
            repository = await _repository(session)
            first = await repository.context_delta(cursor_token=None, max_rows=32)
            second = await repository.context_delta(
                cursor_token=first.next_cursor, max_rows=32
            )
            await session.commit()
            return (
                bool(first.entries),
                first.has_more,
                decode_context_change_cursor(first.next_cursor).last_sequence,
                bool(second.entries),
            )

    has_entries, has_more, last_sequence, replay_has_entries = anyio.run(scenario)

    assert (has_entries, has_more, last_sequence, replay_has_entries) == (
        False,
        False,
        0,
        False,
    )


def test_context_delta_records_archived_transition_with_content_hash() -> None:
    """Archiving a context should record one sequence-ordered archived entry."""

    async def scenario() -> tuple[str, int, str, str]:
        async with _postgres_session() as session:
            repository = await _repository(session)
            seeded = await seed_context(
                session,
                kind=ContextKind.HANDOFF,
                title="Delta archive handoff",
                content="# Delta archive\n\nBody that gets hashed.",
            )
            await session.commit()

            archived = await repository.archive(seeded.id)
            await session.commit()

            page = await _full_delta_page(session)
            entry = page.entries[0]
            await session.commit()
            return (
                entry.change_kind,
                entry.sequence,
                entry.content_hash.hex(),
                context_change_content_hash(archived.content).hex(),
            )

    change_kind, sequence, stored_hash, expected_hash = anyio.run(scenario)

    assert change_kind == "archived"
    assert sequence == 1
    assert stored_hash == expected_hash


def test_context_delta_ignores_unhooked_seeds_and_records_deletes() -> None:
    """Only hooked SQL mutation sites produce entries; deletes stay visible."""

    async def scenario() -> tuple[int, int, str, str | None]:
        async with _postgres_session() as session:
            repository = await _repository(session)
            doomed = await seed_context(
                session,
                kind=ContextKind.PLAN,
                title="Doomed plan",
                content="# Doomed plan\n\nDeleted later.",
            )
            await seed_context(
                session,
                kind=ContextKind.PLAN,
                title="Untouched plan",
                content="# Untouched plan\n\nNever mutated.",
            )
            await session.commit()

            before = await _full_delta_page(session)
            await repository.delete(doomed.id)
            await session.commit()

            page = await _full_delta_page(session)
            gone = await repository.get(doomed.id)
            await session.commit()
            return (
                len(before.entries),
                len(page.entries),
                page.entries[0].change_kind,
                None if gone is None else gone.id,
            )

    seeded_entry_count, deleted_entry_count, deleted_kind, surviving_id = anyio.run(
        scenario
    )

    assert seeded_entry_count == 0
    assert deleted_entry_count == 1
    assert deleted_kind == "deleted"
    assert surviving_id is None


def test_context_delta_orders_by_sequence_for_identical_timestamps() -> None:
    """Identical recorded_at values must not reorder sequence-ordered entries."""

    async def scenario() -> tuple[int, int, str, str]:
        async with _postgres_session() as session:
            first = await seed_context(session, title="First", content="# First")
            second = await seed_context(session, title="Second", content="# Second")
            identical_stamp = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
            await record_context_change(
                session,
                context_id=first.id,
                change_kind=ContextChangeKind.ARCHIVED,
                content_hash=context_change_content_hash(first.content),
                recorded_at=identical_stamp,
            )
            await record_context_change(
                session,
                context_id=second.id,
                change_kind=ContextChangeKind.DELETED,
                content_hash=context_change_content_hash(second.content),
                recorded_at=identical_stamp,
            )
            await session.commit()

            page = await _full_delta_page(session)
            entry_a, entry_b = page.entries
            await session.commit()
            return (
                entry_a.sequence,
                entry_b.sequence,
                entry_a.context_id,
                entry_b.context_id,
            )

    first_sequence, second_sequence, first_context, second_context = anyio.run(scenario)

    assert first_sequence < second_sequence
    assert first_context != second_context


def test_context_delta_pagination_resumes_exactly_without_loss_or_duplicates() -> None:
    """Paging with max_rows must deliver every entry exactly once, in order."""

    async def scenario() -> tuple[list[int], bool]:
        async with _postgres_session() as session:
            repository = await _repository(session)
            for index in range(5):
                seeded = await seed_context(
                    session, title=f"Paged handoff {index}", content=f"# Page {index}"
                )
                await repository.archive(seeded.id)
                await session.commit()

            sequences: list[int] = []
            cursor: str | None = None
            while True:
                page = await repository.context_delta(cursor_token=cursor, max_rows=2)
                sequences.extend(entry.sequence for entry in page.entries)
                if not page.has_more:
                    return sequences, False
                cursor = page.next_cursor

    sequences, tail_has_more = anyio.run(scenario)

    assert len(sequences) == 5
    assert sequences == sorted(set(sequences))
    assert tail_has_more is False


def test_context_delta_rejects_corrupt_foreign_and_stale_cursors() -> None:
    """Typed errors must reject corrupt tokens and foreign scope/version tokens."""

    async def scenario() -> tuple[str, str, str]:
        async with _postgres_session() as session:
            repository = await _repository(session)
            outcomes = []
            for token in (
                "not-a-valid-cursor-token!!!",
                _foreign_scope_token("other-consumer-scope"),
                _foreign_scope_token(CONTEXT_CHANGE_LOG_SCOPE, version=99),
            ):
                try:
                    await repository.context_delta(cursor_token=token, max_rows=32)
                    outcomes.append("accepted")
                except ContextChangeCursorInvalidError:
                    outcomes.append("invalid")
                except ContextChangeCursorResyncRequiredError:
                    outcomes.append("resync")
            await session.commit()
            return cast(tuple[str, str, str], tuple(outcomes))

    corrupt, foreign_scope, stale_version = anyio.run(scenario)

    assert corrupt == "invalid"
    assert foreign_scope == "resync"
    assert stale_version == "resync"


def test_context_delta_replay_is_idempotent_and_never_writes() -> None:
    """Re-reading one cursor must return identical entries and write nothing."""

    async def scenario() -> tuple[list[int], list[int], int]:
        async with _postgres_session() as session:
            repository = await _repository(session)
            seeded = await seed_context(
                session, title="Replay handoff", content="# Replay"
            )
            await repository.archive(seeded.id)
            await session.commit()

            first = await repository.context_delta(cursor_token=None, max_rows=32)
            rows_after_first = await session.scalar(
                text("SELECT count(*) FROM context_change_log")
            )
            second = await repository.context_delta(cursor_token=None, max_rows=32)
            rows_after_second = await session.scalar(
                text("SELECT count(*) FROM context_change_log")
            )
            await session.commit()
            return (
                [entry.sequence for entry in first.entries],
                [entry.sequence for entry in second.entries],
                int(rows_after_second or 0) - int(rows_after_first or 0),
            )

    first_sequences, second_sequences, row_delta = anyio.run(scenario)

    assert first_sequences == second_sequences
    assert row_delta == 0


def test_archived_mutation_rollback_leaves_change_log_empty() -> None:
    """A rolled-back mutation must roll its change record and sequence back too."""

    async def scenario() -> tuple[int, int]:
        async with _postgres_session() as session:
            repository = await _repository(session)
            seeded = await seed_context(
                session, title="Rollback handoff", content="# Rollback"
            )
            await session.commit()

            await repository.archive(seeded.id)
            await session.rollback()

            empty = await _full_delta_page(session)
            await repository.archive(seeded.id)
            await session.commit()
            committed = await _full_delta_page(session)
            await session.commit()
            return len(empty.entries), len(committed.entries)

    empty_count, committed_count = anyio.run(scenario)

    assert empty_count == 0
    assert committed_count == 1


def test_context_delta_rejects_max_rows_outside_bounded_contract() -> None:
    """max_rows beyond the 64-row cap must fail validation, not truncate silently."""

    async def scenario() -> str:
        async with _postgres_session() as session:
            repository = await _repository(session)
            try:
                await repository.context_delta(cursor_token=None, max_rows=65)
            except Exception as exc:
                await session.commit()
                return type(exc).__name__
            await session.commit()
            return "accepted"

    outcome = anyio.run(scenario)

    assert outcome == "MemoryContextValidationError"


def test_context_change_content_hash_is_deterministic_32_bytes() -> None:
    """Content hashing must be deterministic and produce 32-byte digests."""
    first = context_change_content_hash("# Same content")
    second = context_change_content_hash("# Same content")
    other = context_change_content_hash("# Other content")

    assert first == second
    assert first != other
    assert len(first) == 32
