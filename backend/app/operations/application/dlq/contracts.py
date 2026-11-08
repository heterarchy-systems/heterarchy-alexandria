"""Typed callbacks shared by maintenance dead-letter owners."""

from collections.abc import Awaitable, Callable

from app.obsidian.domain.contracts.obsidian_batch_contracts import (
    BatchWriteOperation,
)
from app.obsidian.domain.entities.obsidian_mutation_outcome import (
    ObsidianMutationOutcome,
)
from app.shared.types.extra_types import JSONObject

PayloadReader = Callable[[str], Awaitable[JSONObject | None]]
ArchiveWriter = Callable[[str, JSONObject], Awaitable[bool]]
ArchiveReader = Callable[[str], Awaitable[JSONObject | None]]
NoteOutcomeReader = Callable[[str], Awaitable[ObsidianMutationOutcome]]
BatchIdentity = Callable[[BatchWriteOperation], tuple[str, str]]
