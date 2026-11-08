"""Compact source review must share the composed filesystem lock owner."""

from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import anyio
from dependency_injector import providers
from tests.config_test_data import (
    embedding_config_values,
    vault_config_values,
)
from tests.memory.test_memory_compact_service import _create

from app.memory.containers import MemoryContainer
from app.memory.domain.event_enum.memory_compact_enums import MemoryCompactStatus
from app.memory.domain.repositories.memory_compacts.memory_compact_repository_contracts import (
    MemoryCompactSourceRefCreate,
)
from app.platform.config.memory_config import EmbeddingConfig
from app.platform.config.vault_config import VaultConfig


def test_composed_compact_review_can_read_another_compact(tmp_path: Path) -> None:
    """A review and concurrent reads complete when a source is another compact."""
    container = MemoryContainer(
        embedding_config=EmbeddingConfig(_env_file=None, **embedding_config_values()),
        vault_config=VaultConfig(
            _env_file=None,
            **vault_config_values(
                obsidian_vault_path=str(tmp_path),
                memory_compact_note_dir="Memory Compacts",
            ),
        ),
    )
    # These external source owners are unused by a compact-only source graph.
    container.obsidian_service.override(providers.Object(None))
    container.context_service.override(providers.Object(None))

    async def scenario() -> None:
        service = container.memory_compact_service()
        source = await service.create(_create(MemoryCompactStatus.DRAFT))
        candidate = await service.create(
            replace(
                _create(MemoryCompactStatus.DRAFT),
                markdown_body=source.markdown_body + "\nFollow-up evidence.\n",
                source_refs=(
                    MemoryCompactSourceRefCreate(
                        source_type="memory_compact",
                        source_id=source.id,
                        title="Previous compact",
                        detail_path=f"/memory/compacts/{source.id}",
                        source_hash=sha256(source.markdown_body.encode()).hexdigest(),
                    ),
                ),
            )
        )
        with anyio.fail_after(2):
            review = await service.review(candidate.id)
            assert not review.missing_refs
            assert not review.stale_reasons
            async with anyio.create_task_group() as group:
                group.start_soon(service.review, candidate.id)
                group.start_soon(container.memory_compact_service().list_compacts)
        assert len(list(tmp_path.rglob("*.md"))) == 2

    anyio.run(scenario)
