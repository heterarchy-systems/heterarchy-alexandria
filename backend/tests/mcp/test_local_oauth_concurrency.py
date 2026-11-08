"""PostgreSQL concurrency contracts for single-use OAuth credentials."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.mcp_server.local_oauth.contracts import (
    LocalMcpOAuthSettings,
    LocalOAuthAuthorizationCodeRecord,
)
from app.mcp_server.local_oauth.local_oauth_enums import LocalOAuthTokenKind
from app.mcp_server.local_oauth.orm import (
    McpOAuthAuthorizationCodeORM,
    McpOAuthAuthorizationRequestORM,
    McpOAuthClientORM,
    McpOAuthPairingCodeORM,
    McpOAuthTokenORM,
)
from app.mcp_server.local_oauth.persistence.local_oauth_grant_repository import (
    LocalOAuthGrantRepository,
)
from app.mcp_server.local_oauth.provider_approval import (
    LocalMcpOAuthApprovalService,
    LocalOAuthApprovalError,
    hash_opaque_value,
)
from app.mcp_server.local_oauth.repository import LocalMcpOAuthRepository

_CLIENT_NAME = "oauth-race-client"
_RESOURCE = "https://alexandria.example/mcp"
_SCOPES = ["alexandria:mcp", "offline_access"]
_WAIT_TIMEOUT_SECONDS = 5.0


def _session_factory(
    database_url: str,
) -> tuple[object, async_sessionmaker[AsyncSession], str]:
    application_name = f"oauth-race-{uuid4().hex}"
    engine = create_async_engine(
        database_url,
        pool_size=4,
        max_overflow=0,
        connect_args={"server_settings": {"application_name": application_name}},
    )
    return engine, async_sessionmaker(engine, expire_on_commit=False), application_name


async def _seed_client(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session, session.begin():
        session.add(
            McpOAuthClientORM(
                client_id=_CLIENT_NAME,
                client_secret_ciphertext=None,
                client_metadata={"client_name": "OAuth race test"},
                issued_at=1,
                secret_expires_at=None,
            )
        )


async def _wait_for_lock_waiters(
    session_factory: async_sessionmaker[AsyncSession],
    application_name: str,
    expected: int,
) -> None:
    """Wait until every requested transaction is demonstrably blocked in PostgreSQL."""
    deadline = asyncio.get_running_loop().time() + _WAIT_TIMEOUT_SECONDS
    statement = text(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE application_name = :application_name "
        "AND state = 'active' AND wait_event_type = 'Lock'"
    )
    while asyncio.get_running_loop().time() < deadline:
        async with session_factory() as observer:
            count = await observer.scalar(
                statement, {"application_name": application_name}
            )
        if count is not None and int(count) >= expected:
            return
        await asyncio.sleep(0)
    raise AssertionError(
        f"PostgreSQL did not expose {expected} lock-waiting OAuth sessions"
    )


async def _run_two_while_row_is_locked(
    session_factory: async_sessionmaker[AsyncSession],
    application_name: str,
    row_lock_query: object,
    first_operation: Callable[[], Awaitable[object]],
    second_operation: Callable[[], Awaitable[object]],
) -> tuple[object, object]:
    """Hold one row lock until both OAuth transactions are queued in PostgreSQL."""
    async with session_factory() as blocker:
        await blocker.begin()
        row = await blocker.scalar(row_lock_query)
        assert row is not None
        first = asyncio.create_task(first_operation())
        second = asyncio.create_task(second_operation())
        try:
            await _wait_for_lock_waiters(session_factory, application_name, 2)
        except BaseException:
            await blocker.rollback()
            await asyncio.gather(first, second, return_exceptions=True)
            raise
        await blocker.rollback()
    results = await asyncio.gather(first, second, return_exceptions=True)
    failures = [result for result in results if isinstance(result, BaseException)]
    assert failures == []
    first_result, second_result = results
    return first_result, second_result


async def _seed_authorization_code(
    session_factory: async_sessionmaker[AsyncSession], code_hash: str, now: int
) -> None:
    await _seed_client(session_factory)
    async with session_factory() as session, session.begin():
        session.add(
            McpOAuthAuthorizationCodeORM(
                code_hash=code_hash,
                client_id=_CLIENT_NAME,
                scopes=_SCOPES,
                code_challenge="pkce-challenge",
                redirect_uri="https://client.example/callback",
                redirect_uri_provided_explicitly=True,
                resource=_RESOURCE,
                expires_at=now + 600,
                consumed_at=None,
            )
        )


async def _seed_token_family(
    session_factory: async_sessionmaker[AsyncSession],
    access_hash: str,
    refresh_hash: str,
    family_id: str,
    now: int,
) -> None:
    await _seed_client(session_factory)
    async with session_factory() as session, session.begin():
        session.add_all(
            (
                McpOAuthTokenORM(
                    token_hash=access_hash,
                    token_kind=LocalOAuthTokenKind.ACCESS.value,
                    family_id=family_id,
                    client_id=_CLIENT_NAME,
                    scopes=_SCOPES,
                    resource=_RESOURCE,
                    expires_at=now + 600,
                    revoked_at=None,
                    created_at=now,
                ),
                McpOAuthTokenORM(
                    token_hash=refresh_hash,
                    token_kind=LocalOAuthTokenKind.REFRESH.value,
                    family_id=family_id,
                    client_id=_CLIENT_NAME,
                    scopes=_SCOPES,
                    resource=_RESOURCE,
                    expires_at=now + 600,
                    revoked_at=None,
                    created_at=now,
                ),
            )
        )


async def _family_token_state(
    session_factory: async_sessionmaker[AsyncSession], family_id: str
) -> tuple[int, int]:
    async with session_factory() as session:
        rows = tuple(
            (
                await session.scalars(
                    select(McpOAuthTokenORM).where(
                        McpOAuthTokenORM.family_id == family_id
                    )
                )
            ).all()
        )
    active = sum(row.revoked_at is None for row in rows)
    return len(rows), active


def test_concurrent_authorization_code_exchange_consumes_one_code_once() -> None:
    """Two separate grants cannot exchange one authorization code successfully."""

    async def scenario(database_url: str) -> None:
        engine, sessions, application_name = _session_factory(database_url)
        raw_code = "single-use-authorization-code"
        code_hash = hash_opaque_value(raw_code)
        now = int(time.time())
        try:
            await _seed_authorization_code(sessions, code_hash, now)
            repository = LocalOAuthGrantRepository(sessions)

            async def exchange(access: str, refresh: str, family: str):
                return await repository.exchange_authorization_code(
                    code_hash=code_hash,
                    access_token_hash=hash_opaque_value(access),
                    refresh_token_hash=hash_opaque_value(refresh),
                    family_id=family,
                    access_expires_at=now + 300,
                    refresh_expires_at=now + 600,
                    now=now,
                )

            first, second = await _run_two_while_row_is_locked(
                sessions,
                application_name,
                select(McpOAuthAuthorizationCodeORM)
                .where(McpOAuthAuthorizationCodeORM.code_hash == code_hash)
                .with_for_update(),
                lambda: exchange("access-1", "refresh-1", "family-1"),
                lambda: exchange("access-2", "refresh-2", "family-2"),
            )
            assert (
                sum(
                    isinstance(result, LocalOAuthAuthorizationCodeRecord)
                    for result in (first, second)
                )
                == 1
            )
            winner = (
                "family-1"
                if isinstance(first, LocalOAuthAuthorizationCodeRecord)
                else "family-2"
            )
            assert await _family_token_state(sessions, winner) == (2, 2)
            loser = "family-2" if winner == "family-1" else "family-1"
            assert await _family_token_state(sessions, loser) == (0, 0)
        finally:
            await engine.dispose()

    import os

    asyncio.run(scenario(os.environ["DATABASE_URL"]))


def test_concurrent_refresh_rotation_issues_one_replacement_pair() -> None:
    """The same refresh token cannot yield two successful rotations."""

    async def scenario(database_url: str) -> None:
        engine, sessions, application_name = _session_factory(database_url)
        now = int(time.time())
        access_hash = hash_opaque_value("original-access")
        refresh_hash = hash_opaque_value("original-refresh")
        family_id = "family-rotate-once"
        try:
            await _seed_token_family(
                sessions, access_hash, refresh_hash, family_id, now
            )
            repository = LocalOAuthGrantRepository(sessions)

            async def rotate(generation: str):
                return await repository.rotate_refresh_token(
                    old_refresh_hash=refresh_hash,
                    access_token_hash=hash_opaque_value(f"{generation}-access"),
                    refresh_token_hash=hash_opaque_value(f"{generation}-refresh"),
                    scopes=tuple(_SCOPES),
                    access_expires_at=now + 300,
                    refresh_expires_at=now + 600,
                    now=now,
                )

            first, second = await _run_two_while_row_is_locked(
                sessions,
                application_name,
                select(McpOAuthTokenORM)
                .where(McpOAuthTokenORM.token_hash == refresh_hash)
                .with_for_update(),
                lambda: rotate("next-1"),
                lambda: rotate("next-2"),
            )
            assert sum(result is not None for result in (first, second)) == 1
            assert await _family_token_state(sessions, family_id) == (4, 2)
        finally:
            await engine.dispose()

    import os

    asyncio.run(scenario(os.environ["DATABASE_URL"]))


def test_concurrent_refresh_rotation_and_revocation_leave_no_active_tokens() -> None:
    """A family revocation serialized with rotation cannot leave a live replacement."""

    async def scenario(database_url: str) -> None:
        engine, sessions, application_name = _session_factory(database_url)
        now = int(time.time())
        access_hash = hash_opaque_value("revoke-access")
        refresh_hash = hash_opaque_value("revoke-refresh")
        family_id = "family-revoke-versus-rotate"
        try:
            await _seed_token_family(
                sessions, access_hash, refresh_hash, family_id, now
            )
            repository = LocalOAuthGrantRepository(sessions)

            async def rotate():
                return await repository.rotate_refresh_token(
                    old_refresh_hash=refresh_hash,
                    access_token_hash=hash_opaque_value("rotated-access"),
                    refresh_token_hash=hash_opaque_value("rotated-refresh"),
                    scopes=tuple(_SCOPES),
                    access_expires_at=now + 300,
                    refresh_expires_at=now + 600,
                    now=now,
                )

            async def revoke():
                await repository.revoke_token_family(access_hash, now)

            rotation_result, _ = await _run_two_while_row_is_locked(
                sessions,
                application_name,
                select(McpOAuthTokenORM)
                .where(McpOAuthTokenORM.token_hash == access_hash)
                .with_for_update(),
                rotate,
                revoke,
            )
            expected_rows = 2 if rotation_result is None else 4
            assert await _family_token_state(sessions, family_id) == (expected_rows, 0)
        finally:
            await engine.dispose()

    import os

    asyncio.run(scenario(os.environ["DATABASE_URL"]))


def test_oauth_mutation_rejects_non_read_committed_isolation() -> None:
    """Grant changes fail before reading or consuming state under repeatable read."""

    async def scenario(database_url: str) -> None:
        engine, sessions, _application_name = _session_factory(database_url)
        engine.update_execution_options(isolation_level="REPEATABLE READ")
        now = int(time.time())
        code_hash = hash_opaque_value("isolation-check-code")
        try:
            await _seed_authorization_code(sessions, code_hash, now)
            repository = LocalOAuthGrantRepository(sessions)

            with pytest.raises(RuntimeError, match="READ COMMITTED"):
                await repository.exchange_authorization_code(
                    code_hash=code_hash,
                    access_token_hash=hash_opaque_value("isolation-check-access"),
                    refresh_token_hash=hash_opaque_value("isolation-check-refresh"),
                    family_id="isolation-check-family",
                    access_expires_at=now + 300,
                    refresh_expires_at=now + 600,
                    now=now,
                )

            assert await _family_token_state(sessions, "isolation-check-family") == (
                0,
                0,
            )
            async with sessions() as session:
                code = await session.get(McpOAuthAuthorizationCodeORM, code_hash)
            assert code is not None
            assert code.consumed_at is None
        finally:
            await engine.dispose()

    import os

    asyncio.run(scenario(os.environ["DATABASE_URL"]))


async def _wait_for_advisory_locks(
    session_factory: async_sessionmaker[AsyncSession],
    application_name: str,
    expected: int,
) -> None:
    """Wait until the named OAuth process holds the aggregate transaction lock."""
    deadline = asyncio.get_running_loop().time() + _WAIT_TIMEOUT_SECONDS
    statement = text(
        "SELECT count(*) FROM pg_locks AS locks "
        "JOIN pg_stat_activity AS activity ON activity.pid = locks.pid "
        "WHERE activity.application_name = :application_name "
        "AND locks.locktype = 'advisory' AND locks.granted"
    )
    while asyncio.get_running_loop().time() < deadline:
        async with session_factory() as observer:
            count = await observer.scalar(
                statement, {"application_name": application_name}
            )
        if count is not None and int(count) >= expected:
            return
        await asyncio.sleep(0)
    raise AssertionError(
        f"PostgreSQL did not expose {expected} OAuth advisory lock holders"
    )


async def _seed_authorization_request(
    session_factory: async_sessionmaker[AsyncSession],
    request_id: str,
    now: int,
) -> None:
    await _seed_client(session_factory)
    async with session_factory() as session, session.begin():
        session.add(
            McpOAuthAuthorizationRequestORM(
                request_id=request_id,
                client_id=_CLIENT_NAME,
                client_name="OAuth race test",
                state=None,
                scopes=_SCOPES,
                code_challenge="pkce-challenge",
                redirect_uri="https://client.example/callback",
                redirect_uri_provided_explicitly=True,
                resource=_RESOURCE,
                expires_at=now + 600,
                approval_attempts=0,
                consumed_at=None,
            )
        )


def test_cancellation_releases_aggregate_lock_while_code_row_remains_blocked() -> None:
    """Cancellation must release the OAuth transaction lock before the row blocker."""

    async def scenario(database_url: str) -> None:
        engine, sessions, application_name = _session_factory(database_url)
        raw_code = "cancelled-authorisation-code"
        code_hash = hash_opaque_value(raw_code)
        now = int(time.time())
        repository = LocalMcpOAuthRepository(sessions)
        blocker = sessions()
        try:
            await _seed_authorization_code(sessions, code_hash, now)
            await blocker.begin()
            assert (
                await blocker.scalar(
                    select(McpOAuthAuthorizationCodeORM)
                    .where(McpOAuthAuthorizationCodeORM.code_hash == code_hash)
                    .with_for_update()
                )
                is not None
            )

            async def exchange_code() -> object:
                return await repository.exchange_authorization_code(
                    code_hash=code_hash,
                    access_token_hash=hash_opaque_value("cancelled-access"),
                    refresh_token_hash=hash_opaque_value("cancelled-refresh"),
                    family_id="cancelled-family",
                    access_expires_at=now + 300,
                    refresh_expires_at=now + 600,
                    now=now,
                )

            exchange = asyncio.create_task(exchange_code())
            try:
                await _wait_for_lock_waiters(sessions, application_name, 1)
                await _wait_for_advisory_locks(sessions, application_name, 1)
            finally:
                exchange.cancel()
                await asyncio.gather(exchange, return_exceptions=True)

            async with asyncio.timeout(_WAIT_TIMEOUT_SECONDS):
                await repository.create_pairing_code(
                    code_hash=hash_opaque_value("independent-pairing-code"),
                    expires_at=now + 300,
                    now=now,
                )

            async with sessions() as verification:
                code = await verification.get(McpOAuthAuthorizationCodeORM, code_hash)
                pairing_count = await verification.scalar(
                    select(func.count()).select_from(McpOAuthPairingCodeORM)
                )
            assert code is not None
            assert code.consumed_at is None
            assert pairing_count == 1
            await blocker.rollback()
            async with sessions() as verification:
                code = await verification.get(McpOAuthAuthorizationCodeORM, code_hash)
                tokens = await _family_token_state(sessions, "cancelled-family")
            assert code is not None
            assert code.consumed_at is None
            assert tokens == (0, 0)
        finally:
            await blocker.rollback()
            await blocker.close()
            await engine.dispose()

    import os

    asyncio.run(scenario(os.environ["DATABASE_URL"]))


def test_approval_rechecks_failed_attempt_limit_after_aggregate_lock_wait() -> None:
    """A valid approval racing the last failed attempt cannot issue an authorization code."""

    async def scenario(database_url: str) -> None:
        engine, sessions, application_name = _session_factory(database_url)
        now = int(time.time())
        request_id = "last-approval-attempt"
        settings = LocalMcpOAuthSettings(
            issuer_url="http://localhost",
            resource_url=_RESOURCE,
            required_scopes=("alexandria:mcp",),
            default_scopes=("alexandria:mcp", "offline_access"),
            access_token_ttl_seconds=3600,
            refresh_token_ttl_seconds=86400,
            authorization_code_ttl_seconds=300,
            approval_ttl_seconds=600,
            pairing_code_ttl_seconds=300,
            max_approval_attempts=1,
            approval_key="oauth-race-test-bootstrap-key",
        )
        repository = LocalMcpOAuthRepository(sessions)
        failure_task: asyncio.Task[int] | None = None
        approval_task: asyncio.Task[str] | None = None
        blocker = sessions()
        try:
            await _seed_authorization_request(sessions, request_id, now)
            await blocker.begin()
            assert (
                await blocker.scalar(
                    select(McpOAuthAuthorizationRequestORM)
                    .where(McpOAuthAuthorizationRequestORM.request_id == request_id)
                    .with_for_update()
                )
                is not None
            )
            failure_task = asyncio.create_task(
                repository.record_failed_approval(
                    request_id=request_id,
                    now=now,
                    max_approval_attempts=1,
                )
            )
            await _wait_for_lock_waiters(sessions, application_name, 1)
            await _wait_for_advisory_locks(sessions, application_name, 1)

            approval_service = LocalMcpOAuthApprovalService(repository, settings)
            approval_task = asyncio.create_task(
                approval_service.approve_authorization(
                    request_id,
                    settings.approval_key,
                )
            )
            await _wait_for_lock_waiters(sessions, application_name, 2)
            await _wait_for_advisory_locks(sessions, application_name, 1)
        finally:
            await blocker.rollback()
            await blocker.close()

        try:
            attempt_count = await failure_task
            assert attempt_count == 1
            with pytest.raises(LocalOAuthApprovalError) as rejected:
                await approval_task
            assert rejected.value.status_code == 429
            async with sessions() as session:
                request = await session.get(
                    McpOAuthAuthorizationRequestORM,
                    request_id,
                )
                issued_codes = await session.scalar(
                    select(func.count())
                    .select_from(McpOAuthAuthorizationCodeORM)
                    .where(McpOAuthAuthorizationCodeORM.client_id == _CLIENT_NAME)
                )
            assert request is not None
            assert request.approval_attempts == 1
            assert request.consumed_at is None
            assert issued_codes == 0
        finally:
            await engine.dispose()

    import os

    asyncio.run(scenario(os.environ["DATABASE_URL"]))
