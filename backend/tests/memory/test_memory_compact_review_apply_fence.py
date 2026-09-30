"""CURRENT promotion review-receipt fence tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import anyio
import httpx
import pytest
from tests.memory.test_memory_compact_service import (
    _compact_body,
    _compact_note_path,
    _create,
    _service,
    _source_ref,
)

from app.mcp_server.backend_api_client import AlexandriaApiClient, AlexandriaApiSettings
from app.mcp_server.tools.memory_compacts.memory_compact_tools import (
    alexandria_mark_memory_compact_current,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_service import (
    MemoryCompactService,
)
from app.memory.application.memory_compacts.lifecycle.memory_compact_signature import (
    compact_state_hash,
    reviewed_compact_hash,
)
from app.memory.application.memory_compacts.review.memory_compact_review_contracts import (
    MemoryCompactSourceObservation,
)
from app.memory.domain.entities.memory_compact import MemoryCompactSourceRef
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.infrastructure.repositories.memory_compact_repository import (
    ObsidianMemoryCompactRepository,
)
from app.shared.exceptions.memory_compact_exceptions import (
    MemoryCompactReviewConflictError,
)


def test_reviewed_hash_binds_body_and_review_outcome(tmp_path: Path) -> None:
    """Different bodies or review outcomes produce different receipt hashes."""

    async def scenario() -> tuple[str, str, str]:
        service = _service(tmp_path / "vault")
        compact = await service.create(_create(MemoryCompactStatus.DRAFT))
        loaded = await service.get(compact.id)
        review = await service.review(compact.id)
        base = reviewed_compact_hash(
            loaded,
            verdict=review.verdict.value,
            total_score=review.total_score,
            max_score=review.max_score,
        )
        same = reviewed_compact_hash(
            loaded,
            verdict=review.verdict.value,
            total_score=review.total_score,
            max_score=review.max_score,
        )
        drifted_body = reviewed_compact_hash(
            replace(loaded, markdown_body=_compact_body() + "drift\n"),
            verdict=review.verdict.value,
            total_score=review.total_score,
            max_score=review.max_score,
        )
        return base, same, drifted_body

    base, same, drifted_body = anyio.run(scenario)

    assert base == same
    assert base != drifted_body


def test_semantic_draft_edit_invalidates_review_and_persists_the_final_body_seal(
    tmp_path: Path,
) -> None:
    from app.memory.interface.schemas.memory_compact.memory_compact_schema import (
        MemoryCompactResponse,
    )

    async def scenario():
        service = _service(tmp_path / "vault")
        previous = await service.create(_create(MemoryCompactStatus.CURRENT))
        draft = await service.create(
            replace(
                _create(MemoryCompactStatus.DRAFT),
                markdown_body=_compact_body() + "\nProject draft facts.\n",
            )
        )
        loaded = await service.get(draft.id)
        reviewed = await service.review(draft.id)
        assert reviewed.review_hash
        edited = await service.edit_draft(
            draft.id,
            _compact_body() + "\nFinal project-specific facts.\n",
            compact_state_hash(loaded),
        )
        assert edited.review_receipt_hash is edited.reviewed_body_hash is None
        with pytest.raises(MemoryCompactReviewConflictError):
            await service.mark_current(
                draft.id, expected_review_hash=reviewed.review_hash
            )
        assert (await service.current(previous.project)).id == previous.id
        current_review = await service.review(draft.id)
        promoted = await service.mark_current(
            draft.id, expected_review_hash=current_review.review_hash
        )
        persisted = await service.get(promoted.id)
        response = MemoryCompactResponse.from_entity(persisted)
        assert response.review_attestation_status == "VERIFIED"
        assert response.reviewed_body_hash == response.current_body_hash
        assert response.review_receipt_hash == current_review.review_hash
        with pytest.raises(MemoryCompactReviewConflictError):
            await service.edit_draft(
                draft.id, "wrong current mutation", compact_state_hash(persisted)
            )

    anyio.run(scenario)


def test_identical_draft_never_deduplicates_into_current(tmp_path: Path) -> None:
    """Draft-only refresh remains editable even when its body matches CURRENT."""

    async def scenario():
        service = _service(tmp_path / "vault")
        current = await service.create(_create(MemoryCompactStatus.CURRENT))
        draft = await service.create(_create(MemoryCompactStatus.DRAFT))
        assert draft.status is MemoryCompactStatus.DRAFT
        assert draft.id != current.id
        assert (await service.current(current.project)).id == current.id
        repeated = await service.create(_create(MemoryCompactStatus.DRAFT))
        assert repeated.id == draft.id
        assert repeated.deduplicated

    anyio.run(scenario)


def test_mark_current_promotes_behind_matching_review_hash(tmp_path: Path) -> None:
    """The admitted review receipt promotes the reviewed body to CURRENT."""

    async def scenario() -> tuple[str, str | None]:
        service = _service(tmp_path / "vault")
        compact = await service.create(_create(MemoryCompactStatus.DRAFT))
        review = await service.review(compact.id)
        receipt = review.review_hash
        promoted = await service.mark_current(compact.id, expected_review_hash=receipt)
        return promoted.status.value, promoted.review_verdict.value

    status_value, verdict_value = anyio.run(scenario)

    assert status_value == "CURRENT"
    assert verdict_value == "pass"


def test_mark_current_rejects_drifted_receipt_and_keeps_previous_current(
    tmp_path: Path,
) -> None:
    """A stale receipt is refused and the previous CURRENT stays in place."""

    async def scenario() -> tuple[str, str]:
        service = _service(tmp_path / "vault")
        previous = await service.create(_create(MemoryCompactStatus.CURRENT))
        draft_payload = _create(MemoryCompactStatus.DRAFT)
        draft_payload = replace(
            draft_payload,
            markdown_body=draft_payload.markdown_body
            + "\n## Next Actions\n- Agent semantic edit draft line.\n",
        )
        draft = await service.create(draft_payload)
        review = await service.review(draft.id)
        receipt = review.review_hash
        note_path = _compact_note_path(tmp_path / "vault", draft.id)
        note_path.write_text(
            note_path.read_text(encoding="utf-8")
            + "Agent semantic edit after review.\n",
            encoding="utf-8",
        )
        try:
            await service.mark_current(draft.id, expected_review_hash=receipt)
            raised = "no-error"
        except MemoryCompactReviewConflictError:
            raised = "conflict"
        still_current = await service.get(previous.id)
        draft_after = await service.get(draft.id)
        return raised, (still_current.status.value, draft_after.status.value)

    raised, states = anyio.run(scenario)

    assert raised == "conflict"
    assert states == ("CURRENT", "DRAFT")


def test_mark_current_adapter_posts_review_hash_fence() -> None:
    """The MCP adapter posts the receipt hash to the mark-current route."""
    recorded: list[httpx.Request] = []

    async def transport(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, content=b'{"id": "compact-1", "status": "CURRENT"}')

    client = AlexandriaApiClient(
        AlexandriaApiSettings(base_url="http://backend:8000", timeout=5.0),
        transport=httpx.MockTransport(transport),
    )

    async def scenario():
        return await alexandria_mark_memory_compact_current(
            client,
            "compact-1",
            expected_review_hash="a" * 64,
        )

    anyio.run(scenario)

    import json

    body = json.loads(recorded[0].content.decode("utf-8"))
    assert recorded[0].url.path.endswith("/memory/compacts/compact-1/mark-current")
    assert body == {"expected_review_hash": "a" * 64}


def test_review_receipt_binds_project_coverage_and_source_identity(
    tmp_path: Path,
) -> None:
    """A review receipt must cover all promotion-relevant compact state."""

    async def scenario() -> tuple[str, str, str, str]:
        service = _service(tmp_path / "vault")
        compact = await service.create(_create(MemoryCompactStatus.DRAFT))
        review = await service.review(compact.id)
        loaded = await service.get(compact.id)
        base = reviewed_compact_hash(
            loaded,
            verdict=review.verdict.value,
            total_score=review.total_score,
            max_score=review.max_score,
        )
        project_drift = reviewed_compact_hash(
            replace(loaded, project="another-project"),
            verdict=review.verdict.value,
            total_score=review.total_score,
            max_score=review.max_score,
        )
        coverage_drift = reviewed_compact_hash(
            replace(loaded, covered_to=loaded.covered_to.replace(day=11)),
            verdict=review.verdict.value,
            total_score=review.total_score,
            max_score=review.max_score,
        )
        source_drift = reviewed_compact_hash(
            replace(
                loaded,
                source_refs=(replace(loaded.source_refs[0], source_hash="changed"),),
            ),
            verdict=review.verdict.value,
            total_score=review.total_score,
            max_score=review.max_score,
        )
        return base, project_drift, coverage_drift, source_drift

    base, project_drift, coverage_drift, source_drift = anyio.run(scenario)

    assert len({base, project_drift, coverage_drift, source_drift}) == 4


def test_review_uses_authoritative_source_reader_over_client_observation(
    tmp_path: Path,
) -> None:
    """Caller-provided source hashes cannot replace an owning source reader."""

    async def source_reader(
        source_ref: MemoryCompactSourceRef,
    ):
        return MemoryCompactSourceObservation(
            source_id=source_ref.source_id,
            detail_path=source_ref.detail_path,
            current_source_hash="canonical-hash",
        )

    async def scenario() -> tuple[str, str]:
        repository = ObsidianMemoryCompactRepository(
            vault_path=tmp_path / "vault",
            relative_dir="Alexandria/Memory Compacts",
        )
        service = MemoryCompactService(
            repository=repository,
            source_reader=source_reader,
        )
        payload = replace(
            _create(MemoryCompactStatus.DRAFT),
            source_refs=(_source_ref(source_hash="canonical-hash"),),
        )
        compact = await service.create(payload)
        review = await service.review(
            compact.id,
            source_observations=(
                MemoryCompactSourceObservation(
                    source_id="ctx-1",
                    detail_path="/memory/contexts/ctx-1",
                    current_source_hash="spoofed-hash",
                ),
            ),
        )
        return review.verdict.value, review.review_hash

    verdict, review_hash = anyio.run(scenario)

    assert verdict == "pass"
    assert len(review_hash) == 64


def test_unavailable_authoritative_source_blocks_review_without_fake_hash(
    tmp_path: Path,
) -> None:
    """An unreadable source is explicit review evidence, never a fake hash."""

    async def source_reader(
        source_ref: MemoryCompactSourceRef,
    ) -> MemoryCompactSourceObservation:
        raise LookupError("source not available")

    async def scenario() -> tuple[str, tuple[str, ...]]:
        service = MemoryCompactService(
            repository=ObsidianMemoryCompactRepository(
                vault_path=tmp_path / "vault",
                relative_dir="Alexandria/Memory Compacts",
            ),
            source_reader=source_reader,
        )
        compact = await service.create(_create(MemoryCompactStatus.DRAFT))
        review = await service.review(compact.id)
        return review.verdict.value, review.stale_reasons

    verdict, stale_reasons = anyio.run(scenario)

    assert verdict == "blocked"
    assert stale_reasons == ("source_unavailable:ctx-1:LookupError",)


def test_fixture_unknown_source_is_unavailable_and_blocks_review(
    tmp_path: Path,
) -> None:
    """Unknown fixture identities cannot silently become synthetic evidence."""

    async def scenario() -> tuple[str, tuple[str, ...]]:
        service = _service(tmp_path / "vault")
        compact = await service.create(
            replace(
                _create(MemoryCompactStatus.DRAFT),
                source_refs=(_source_ref("fixture-source-not-registered"),),
            )
        )
        review = await service.review(compact.id)
        return review.verdict.value, review.stale_reasons

    verdict, stale_reasons = anyio.run(scenario)

    assert verdict == "blocked"
    assert stale_reasons == (
        "source_unavailable:fixture-source-not-registered:fixture_source_missing",
    )


def test_legacy_current_create_is_reviewed_by_authoritative_source_reader(
    tmp_path: Path,
) -> None:
    """Legacy direct CURRENT creation still passes through the source fence."""

    async def source_reader(
        source_ref: MemoryCompactSourceRef,
    ) -> MemoryCompactSourceObservation:
        return MemoryCompactSourceObservation(
            source_id=source_ref.source_id,
            detail_path=source_ref.detail_path,
            current_source_hash="changed",
        )

    async def scenario() -> str:
        service = MemoryCompactService(
            repository=ObsidianMemoryCompactRepository(
                vault_path=tmp_path / "vault",
                relative_dir="Alexandria/Memory Compacts",
            ),
            source_reader=source_reader,
        )
        try:
            await service.create(
                replace(
                    _create(MemoryCompactStatus.CURRENT),
                    source_refs=(_source_ref(source_hash="admitted"),),
                )
            )
        except Exception as exc:
            return type(exc).__name__
        return "no-error"

    assert anyio.run(scenario) == "MemoryCompactValidationError"


def test_promotion_source_drift_is_rejected_under_authoritative_reader(
    tmp_path: Path,
) -> None:
    """A source change after review invalidates the promotion receipt."""
    current_hash = "canonical-before"

    async def source_reader(
        source_ref: MemoryCompactSourceRef,
    ) -> MemoryCompactSourceObservation:
        return MemoryCompactSourceObservation(
            source_id=source_ref.source_id,
            detail_path=source_ref.detail_path,
            current_source_hash=current_hash,
        )

    async def scenario() -> tuple[str, str, str]:
        nonlocal current_hash
        service = MemoryCompactService(
            repository=ObsidianMemoryCompactRepository(
                vault_path=tmp_path / "vault",
                relative_dir="Alexandria/Memory Compacts",
            ),
            source_reader=source_reader,
        )
        previous = await service.create(_create(MemoryCompactStatus.CURRENT))
        draft = await service.create(
            replace(
                _create(MemoryCompactStatus.DRAFT),
                source_refs=(_source_ref(source_hash="canonical-before"),),
            )
        )
        review = await service.review(draft.id)
        current_hash = "canonical-after"
        try:
            await service.mark_current(
                draft.id,
                expected_review_hash=review.review_hash,
            )
        except MemoryCompactReviewConflictError as exc:
            error = str(exc)
        else:
            error = "no-error"
        return (
            error,
            (await service.get(previous.id)).status.value,
            (await service.get(draft.id)).status.value,
        )

    error, previous_status, draft_status = anyio.run(scenario)

    assert "review" in error.lower() or "source" in error.lower()
    assert previous_status == "CURRENT"
    assert draft_status == "DRAFT"


def test_promotion_failure_restores_previous_current_and_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed multi-file promotion restores the exact prior lifecycle state."""

    async def scenario() -> tuple[str, str, str]:
        service = _service(tmp_path / "vault")
        previous = await service.create(_create(MemoryCompactStatus.CURRENT))
        draft = await service.create(
            replace(
                _create(MemoryCompactStatus.DRAFT),
                markdown_body=_compact_body() + "\n- failure candidate.\n",
            )
        )
        review = await service.review(draft.id)
        repository = service._repository
        original_write = repository._store.write
        write_count = 0

        def fail_during_supersede(compact) -> None:
            nonlocal write_count
            write_count += 1
            if write_count == 2:
                raise OSError("simulated supersede failure")
            original_write(compact)

        monkeypatch.setattr(repository._store, "write", fail_during_supersede)
        try:
            await service.mark_current(
                draft.id,
                expected_review_hash=review.review_hash,
            )
        except OSError as exc:
            error = str(exc)
        else:
            error = "no-error"
        return (
            error,
            (await service.get(previous.id)).status.value,
            (await service.get(draft.id)).status.value,
        )

    error, previous_status, draft_status = anyio.run(scenario)

    assert error == "simulated supersede failure"
    assert previous_status == "CURRENT"
    assert draft_status == "DRAFT"


def test_concurrent_promotions_leave_one_current_per_project(tmp_path: Path) -> None:
    """Concurrent reviewed promotions serialize through the existing file lock."""

    async def scenario() -> int:
        vault = tmp_path / "vault"
        first_service = _service(vault)
        second_service = _service(vault)
        first = await first_service.create(_create(MemoryCompactStatus.DRAFT))
        second = await second_service.create(
            replace(
                _create(MemoryCompactStatus.DRAFT),
                markdown_body=_compact_body() + "\n- second candidate.\n",
            )
        )
        first_review = await first_service.review(first.id)
        second_review = await second_service.review(second.id)

        async def promote_first() -> None:
            await first_service.mark_current(
                first.id,
                expected_review_hash=first_review.review_hash,
            )

        async def promote_second() -> None:
            await second_service.mark_current(
                second.id,
                expected_review_hash=second_review.review_hash,
            )

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(promote_first)
            task_group.start_soon(promote_second)
        _current, total = await first_service.list_compacts(
            project="heterarchy-alexandria",
            status=MemoryCompactStatus.CURRENT,
        )
        return total

    assert anyio.run(scenario) == 1
