"""General note-write admission uses the existing durable checkpoint owner."""

from dataclasses import replace
from functools import partial
from hashlib import sha256
from pathlib import Path

import anyio
import anyio.to_thread
from pydantic import TypeAdapter

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianWriteNote,
)
from app.obsidian.domain.entities.obsidian_mutation_outcome import (
    NoteMutationReceipt,
    ObsidianMutationOutcome,
)
from app.obsidian.domain.entities.obsidian_note import ObsidianNote
from app.obsidian.domain.event_enum.obsidian_mutation_enums import (
    ObsidianMutationOutcomeStatus,
)
from app.obsidian.infrastructure.obsidian_report_bundle_run_store import (
    ObsidianReportBundleRunStore,
)
from app.obsidian.infrastructure.obsidian_vault_config_store import (
    ObsidianVaultConfigStore,
)
from app.shared.compute.native_text_hashing import hash_text
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianCheckpointRecoveryRequiredError,
    ObsidianIdempotencyConflictError,
    ObsidianValidationError,
)
from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.types.extra_types import JSONObject

_ADAPTER = TypeAdapter(NoteMutationReceipt)
_MUTATION_ID_PREFIX = "note-write:"


def _is_sha256(value: str | None) -> bool:
    """Return whether a value is an exact lowercase SHA-256 digest."""
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _recovery(checkpoint_id: str) -> ObsidianCheckpointRecoveryRequiredError:
    """Build one fail-closed recovery error for invalid durable evidence."""
    return ObsidianCheckpointRecoveryRequiredError(checkpoint_id)


def _validate_receipt(
    receipt: NoteMutationReceipt,
    *,
    expected_key: str | None = None,
    expected_mutation_id: str | None = None,
) -> NoteMutationReceipt:
    """Validate semantic receipt invariants after typed deserialization.

    Pydantic validates field types, but a typed record can still contain a
    valid-shaped value belonging to another request or an incomplete started
    effect.  Those records must remain recoverable evidence and never become a
    fresh admission or a committed verdict.
    """
    checkpoint_id = expected_mutation_id or receipt.mutation_id
    if not receipt.idempotency_key.strip():
        raise _recovery(checkpoint_id)
    if expected_key is not None and receipt.idempotency_key != expected_key:
        raise _recovery(checkpoint_id)
    if receipt.mutation_id != note_mutation_id(receipt.idempotency_key):
        raise _recovery(checkpoint_id)
    if expected_mutation_id is not None and receipt.mutation_id != expected_mutation_id:
        raise _recovery(checkpoint_id)
    if not _is_sha256(receipt.operation_identity):
        raise _recovery(checkpoint_id)
    for source_hash in (
        receipt.expected_source_hash,
        receipt.previous_source_hash,
        receipt.content_hash,
    ):
        if source_hash is not None and not _is_sha256(source_hash):
            raise _recovery(checkpoint_id)
    if receipt.effect_started and (
        not receipt.canonical_path
        or not receipt.canonical_path.strip()
        or not receipt.note_id
        or not receipt.note_id.strip()
        or not _is_sha256(receipt.expected_source_hash)
    ):
        raise _recovery(checkpoint_id)
    committed_at = receipt.committed_at
    if committed_at is not None and (
        committed_at.tzinfo is None or committed_at.utcoffset() is None
    ):
        raise _recovery(checkpoint_id)
    if receipt.status is ObsidianMutationOutcomeStatus.COMMITTED:
        if not receipt.effect_started or committed_at is None:
            raise _recovery(checkpoint_id)
        if receipt.content_hash is None:
            raise _recovery(checkpoint_id)
    return receipt


def note_mutation_identity(
    payload: ObsidianSaveNote, command: ObsidianWriteNote | None = None
) -> tuple[str, str]:
    """Bind caller semantics to one stable key without volatile server metadata.

    Args:
        payload: Original typed note request before target resolution.
        command: Explicit create/update selector when present.

    Returns:
        Stable idempotency key and operation request fingerprint.
    """
    fields: JSONObject = {
        "title": payload.title,
        "body": payload.body,
        "alexandria_type": payload.alexandria_type.value,
        "note_id": payload.note_id,
        "relative_path": payload.relative_path,
        "tags": list(payload.tags),
        "status": payload.status,
        "project": payload.project,
        "source": payload.source,
        "frontmatter": payload.frontmatter,
        "expected_content_hash": payload.expected_content_hash,
        "write_mode": None if command is None else command.write_mode.value,
        "match_by": None if command is None else command.match_by.value,
        "frontmatter_mode": None if command is None else command.frontmatter_mode.value,
        "provided_fields": None
        if command is None or command.provided_fields is None
        else sorted(command.provided_fields - {"idempotency_key"}),
    }
    identity = sha256(dumps_canonical_json(fields)).hexdigest()
    key = (
        payload.idempotency_key
        if payload.idempotency_key is not None
        else "implicit:" + identity
    )
    if not key.strip() or len(key) > 512:
        raise ObsidianValidationError(
            "idempotency_key must contain 1..512 nonblank characters"
        )
    return key, identity


def note_mutation_id(key: str) -> str:
    """Derive a non-secret receipt selector from the retry-stable key.

    Args:
        key: Caller or request-derived idempotency identity.

    Returns:
        Stable namespaced mutation identifier.
    """
    return _MUTATION_ID_PREFIX + sha256(key.encode("utf-8")).hexdigest()


def receipt_outcome(
    receipt: NoteMutationReceipt,
    *,
    replayed: bool = False,
    evidence: tuple[str, ...] = (),
) -> ObsidianMutationOutcome:
    """Project admission evidence into the common public outcome contract.

    Args:
        receipt: Current persisted note receipt.
        replayed: Whether the writer returned a readback instead of writing.
        evidence: Exact readback evidence codes.

    Returns:
        Immutable common mutation verdict.
    """
    return ObsidianMutationOutcome(
        operation="note_write",
        idempotency_key=receipt.idempotency_key,
        status=receipt.status,
        checkpoint_state="write_started" if receipt.effect_started else "admitted",
        canonical_path=receipt.canonical_path,
        note_id=receipt.note_id,
        content_hash=receipt.content_hash,
        version=receipt.version,
        mutation_id=receipt.mutation_id,
        operation_identity=receipt.operation_identity,
        committed_at=receipt.committed_at,
        error_summary=receipt.error_summary,
        replayed=replayed,
        evidence=evidence,
    )


class NoteMutationReceipts:
    """Bound durable effect evidence; callers hold existing maintenance ownership."""

    def __init__(self, vault_config_store: ObsidianVaultConfigStore) -> None:
        """Initialize the existing checkpoint location.

        Args:
            vault_config_store: Canonical Vault location owner.
        """
        self._vault_config_store = vault_config_store

    async def load(self, key: str) -> NoteMutationReceipt | None:
        """Read the typed receipt without changing state.

        Args:
            key: Original idempotency identity.

        Returns:
            Current receipt, or None before admission.
        """
        if not key.strip():
            raise ObsidianValidationError("idempotency_key must not be blank")
        mutation_id = note_mutation_id(key)
        return await self._load_by_mutation_id(
            mutation_id,
            expected_key=key,
        )

    async def load_by_mutation_id(
        self,
        mutation_id: str,
    ) -> NoteMutationReceipt | None:
        """Read one receipt by its namespaced, retry-safe mutation identifier.

        The selector is deliberately narrower than the underlying run-store
        key.  A caller cannot turn an arbitrary checkpoint into a note-write
        outcome, and a valid file whose embedded identity disagrees with the
        selector is treated as recovery-required evidence.
        """
        if not _is_note_mutation_id(mutation_id):
            raise ObsidianValidationError("mutation_id must be note-write:<sha256>")
        return await self._load_by_mutation_id(mutation_id)

    async def admit(self, key: str, identity: str) -> NoteMutationReceipt:
        """Persist admission before resolving or mutating any source.

        Args:
            key: Original idempotency identity.
            identity: Canonical request fingerprint.

        Returns:
            Existing exact admission, or a newly durable pre-effect record.

        Raises:
            ObsidianIdempotencyConflictError: When the key names another request.
        """
        existing = await self.load(key)
        if existing is not None:
            if existing.operation_identity != identity:
                raise ObsidianIdempotencyConflictError
            return existing
        receipt = NoteMutationReceipt(
            idempotency_key=key,
            mutation_id=note_mutation_id(key),
            operation_identity=identity,
            status=ObsidianMutationOutcomeStatus.NOT_COMMITTED,
        )
        await self.save(receipt)
        return receipt

    async def started(
        self,
        receipt: NoteMutationReceipt,
        *,
        path: str,
        note_id: str,
        document: str,
        absolute: Path,
    ) -> None:
        """Fence the exact intended bytes immediately before source replacement.

        Args:
            receipt: Admitted request identity.
            path: Exact canonical source path.
            note_id: Resolved source identity.
            document: Intended UTF-8 document bytes.
            absolute: Resolved filesystem effect target.
        """
        previous = await anyio.to_thread.run_sync(_source_hash, absolute)
        await self.save(
            replace(
                receipt,
                effect_started=True,
                status=ObsidianMutationOutcomeStatus.UNKNOWN,
                canonical_path=path,
                note_id=note_id,
                expected_source_hash=hash_text(document),
                previous_source_hash=previous,
            )
        )

    async def completed(
        self, receipt: NoteMutationReceipt, note: ObsidianNote
    ) -> ObsidianMutationOutcome:
        """Record observed source completion without claiming projection durability.

        Args:
            receipt: Admitted write identity.
            note: Observed canonical source result.

        Returns:
            Common committed receipt for this primary source effect.
        """
        current = await self.load(receipt.idempotency_key) or receipt
        absolute = self._vault_config_store.current().vault_path / note.relative_path
        source_hash = await anyio.to_thread.run_sync(_source_hash, absolute)
        if source_hash is None:
            raise ObsidianValidationError("MUTATION_SOURCE_READBACK_REQUIRED")
        if current.effect_started and source_hash != current.expected_source_hash:
            raise ObsidianValidationError("MUTATION_SOURCE_DRIFTED_BEFORE_RECEIPT")
        version = note.frontmatter.get("version")
        completed = replace(
            receipt,
            status=ObsidianMutationOutcomeStatus.COMMITTED,
            effect_started=True,
            canonical_path=note.relative_path,
            note_id=note.note_id,
            expected_source_hash=source_hash,
            content_hash=note.content_hash,
            version=version
            if isinstance(version, int) and not isinstance(version, bool)
            else None,
            committed_at=note.modified_at,
            error_summary=None,
        )
        await self.save(completed)
        return receipt_outcome(
            completed,
            evidence=("primary_source_committed", "projection_status_is_separate"),
        )

    async def observe(
        self, receipt: NoteMutationReceipt, note: ObsidianNote | None
    ) -> ObsidianMutationOutcome:
        """Reconcile a started effect against exact bytes without writing a receipt.

        Args:
            receipt: Existing durable intent.
            note: Exact canonical readback; None when the target is absent.

        Returns:
            Primary-effect verdict, retaining uncertainty on absent/changed sources.
        """
        if not receipt.effect_started:
            return receipt_outcome(receipt, evidence=("effect_not_started",))
        if note is None:
            return receipt_outcome(
                replace(receipt, status=ObsidianMutationOutcomeStatus.UNKNOWN),
                evidence=("started_source_absent",),
            )
        source_hash = await anyio.to_thread.run_sync(
            _source_hash,
            self._vault_config_store.current().vault_path / note.relative_path,
        )
        if note.note_id != receipt.note_id:
            return receipt_outcome(
                replace(receipt, status=ObsidianMutationOutcomeStatus.CONFLICTED),
                evidence=("source_identity_changed",),
            )
        if source_hash == receipt.expected_source_hash:
            version = note.frontmatter.get("version")
            return receipt_outcome(
                replace(
                    receipt,
                    status=ObsidianMutationOutcomeStatus.COMMITTED,
                    content_hash=note.content_hash,
                    committed_at=receipt.committed_at or note.modified_at,
                    version=version
                    if isinstance(version, int) and not isinstance(version, bool)
                    else None,
                ),
                evidence=(
                    "exact_source_matches_intent",
                    "projection_status_is_separate",
                ),
            )
        if (
            receipt.status is not ObsidianMutationOutcomeStatus.COMMITTED
            and source_hash == receipt.previous_source_hash
            and source_hash is not None
        ):
            return receipt_outcome(
                replace(receipt, status=ObsidianMutationOutcomeStatus.NOT_COMMITTED),
                evidence=("exact_source_unchanged",),
            )
        return receipt_outcome(
            replace(receipt, status=ObsidianMutationOutcomeStatus.CONFLICTED),
            evidence=("source_changed_since_admission",),
        )

    async def failed(
        self, receipt: NoteMutationReceipt, error: Exception, *, conflicted: bool
    ) -> None:
        """Preserve unknown effects; never infer no commit from a transport error.

        Args:
            receipt: Original admitted write identity.
            error: Observed pipeline failure category.
            conflicted: Whether the failure definitively preceded effect admission.
        """
        current = await self.load(receipt.idempotency_key) or receipt
        status = (
            ObsidianMutationOutcomeStatus.UNKNOWN
            if current.effect_started
            else ObsidianMutationOutcomeStatus.CONFLICTED
            if conflicted
            else ObsidianMutationOutcomeStatus.NOT_COMMITTED
        )
        await self.save(
            replace(current, status=status, error_summary=type(error).__name__)
        )

    async def save(self, receipt: NoteMutationReceipt) -> None:
        """Persist typed evidence using the existing fsync checkpoint primitive.

        Args:
            receipt: Owned immutable mutation state to record.
        """
        _validate_receipt(receipt)
        await anyio.to_thread.run_sync(
            partial(self._store().save_typed, receipt.mutation_id, receipt, _ADAPTER)
        )

    async def _load_by_mutation_id(
        self,
        mutation_id: str,
        *,
        expected_key: str | None = None,
    ) -> NoteMutationReceipt | None:
        """Load and semantically bind one existing typed receipt."""
        receipt = await anyio.to_thread.run_sync(
            partial(self._store().load_typed, mutation_id, _ADAPTER)
        )
        if receipt is None:
            return None
        return _validate_receipt(
            receipt,
            expected_key=expected_key,
            expected_mutation_id=mutation_id,
        )

    def _store(self) -> ObsidianReportBundleRunStore:
        return ObsidianReportBundleRunStore(
            vault_path=self._vault_config_store.current().vault_path
        )


def _source_hash(path: Path) -> str | None:
    try:
        return hash_text(path.read_bytes().decode("utf-8"))
    except FileNotFoundError:
        return None


def _is_note_mutation_id(value: str) -> bool:
    """Return whether a direct selector is the exact note-write namespace."""
    return value.startswith(_MUTATION_ID_PREFIX) and _is_sha256(
        value.removeprefix(_MUTATION_ID_PREFIX)
    )
