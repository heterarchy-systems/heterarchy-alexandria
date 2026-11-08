"""Retry-safe note mutation identity and durable receipt validation."""

from hashlib import sha256

from typing_extensions import TypedDict

from app.obsidian.domain.contracts.obsidian_contracts import (
    ObsidianSaveNote,
    ObsidianWriteNote,
)
from app.obsidian.domain.entities.obsidian_mutation_outcome import NoteMutationReceipt
from app.obsidian.domain.event_enum.obsidian_mutation_enums import (
    ObsidianMutationOutcomeStatus,
)
from app.shared.exceptions.obsidian_exceptions import (
    ObsidianCheckpointRecoveryRequiredError,
    ObsidianValidationError,
)
from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.types.extra_types import JSONObject, JSONValue

_MUTATION_ID_PREFIX = "note-write:"


class NoteMutationIdentityPayloadDict(TypedDict, closed=True):
    """Ordered canonical request fields hashed for note-write idempotency."""

    title: str
    body: str
    alexandria_type: str
    note_id: str | None
    relative_path: str | None
    tags: list[str]
    status: str
    project: str | None
    source: str
    frontmatter: JSONObject
    expected_content_hash: str | None
    write_mode: str | None
    match_by: str | None
    frontmatter_mode: str | None
    provided_fields: list[str] | None


class ReceiptIdentityPolicy:
    """Derive retry identities and reject receipts bound to another operation."""

    @staticmethod
    def is_sha256(value: str | None) -> bool:
        """Return whether a value is an exact lowercase SHA-256 digest."""
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    @staticmethod
    def validate_receipt(
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
            raise ObsidianCheckpointRecoveryRequiredError(checkpoint_id)
        if expected_key is not None and receipt.idempotency_key != expected_key:
            raise ObsidianCheckpointRecoveryRequiredError(checkpoint_id)
        if receipt.mutation_id != ReceiptIdentityPolicy.mutation_id(
            receipt.idempotency_key
        ):
            raise ObsidianCheckpointRecoveryRequiredError(checkpoint_id)
        if (
            expected_mutation_id is not None
            and receipt.mutation_id != expected_mutation_id
        ):
            raise ObsidianCheckpointRecoveryRequiredError(checkpoint_id)
        if not ReceiptIdentityPolicy.is_sha256(receipt.operation_identity):
            raise ObsidianCheckpointRecoveryRequiredError(checkpoint_id)
        for source_hash in (
            receipt.expected_source_hash,
            receipt.previous_source_hash,
            receipt.content_hash,
        ):
            if source_hash is not None and not ReceiptIdentityPolicy.is_sha256(
                source_hash
            ):
                raise ObsidianCheckpointRecoveryRequiredError(checkpoint_id)
        if receipt.effect_started and (
            not receipt.canonical_path
            or not receipt.canonical_path.strip()
            or not receipt.note_id
            or not receipt.note_id.strip()
            or not ReceiptIdentityPolicy.is_sha256(receipt.expected_source_hash)
        ):
            raise ObsidianCheckpointRecoveryRequiredError(checkpoint_id)
        committed_at = receipt.committed_at
        if committed_at is not None and (
            committed_at.tzinfo is None or committed_at.utcoffset() is None
        ):
            raise ObsidianCheckpointRecoveryRequiredError(checkpoint_id)
        if receipt.status is ObsidianMutationOutcomeStatus.COMMITTED:
            if not receipt.effect_started or committed_at is None:
                raise ObsidianCheckpointRecoveryRequiredError(checkpoint_id)
            if receipt.content_hash is None:
                raise ObsidianCheckpointRecoveryRequiredError(checkpoint_id)
        return receipt

    @staticmethod
    def request_identity(
        payload: ObsidianSaveNote, command: ObsidianWriteNote | None = None
    ) -> tuple[str, str]:
        """Bind caller semantics to one stable key without volatile server metadata.

        Args:
            payload: Original typed note request before target resolution.
            command: Explicit create/update selector when present.

        Returns:
            Stable idempotency key and operation request fingerprint.
        """
        fields = NoteMutationIdentityPayloadDict(
            title=payload.title,
            body=payload.body,
            alexandria_type=payload.alexandria_type.value,
            note_id=payload.note_id,
            relative_path=payload.relative_path,
            tags=list(payload.tags),
            status=payload.status,
            project=payload.project,
            source=payload.source,
            frontmatter=payload.frontmatter,
            expected_content_hash=payload.expected_content_hash,
            write_mode=None if command is None else command.write_mode.value,
            match_by=None if command is None else command.match_by.value,
            frontmatter_mode=None
            if command is None
            else command.frontmatter_mode.value,
            provided_fields=None
            if command is None or command.provided_fields is None
            else sorted(command.provided_fields - {"idempotency_key"}),
        )
        identity = sha256(
            dumps_canonical_json(dict[str, JSONValue](**fields))
        ).hexdigest()
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

    @staticmethod
    def mutation_id(key: str) -> str:
        """Derive a non-secret receipt selector from the retry-stable key.

        Args:
            key: Caller or request-derived idempotency identity.

        Returns:
            Stable namespaced mutation identifier.
        """
        return _MUTATION_ID_PREFIX + sha256(key.encode("utf-8")).hexdigest()

    @staticmethod
    def is_mutation_id(value: str) -> bool:
        """Return whether a direct selector is the exact note-write namespace."""
        return value.startswith(
            _MUTATION_ID_PREFIX
        ) and ReceiptIdentityPolicy.is_sha256(value.removeprefix(_MUTATION_ID_PREFIX))
