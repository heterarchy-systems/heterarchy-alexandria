"""Runtime provenance and retrieval-canary readiness response contracts."""

from __future__ import annotations

from typing import Annotated

from app.memory.domain.entities.context_projection_integrity import (
    ContextProjectionIntegrityFailure,
    ContextProjectionIntegritySnapshot,
)
from app.memory.domain.event_enum.context_enums import RagStrategy
from app.operations.domain.entities.operational_retrieval_canary import (
    OperationalRetrievalCanaryResult,
    OperationalRetrievalCanarySnapshot,
)
from app.operations.domain.entities.operational_runtime_provenance import (
    OperationalRuntimeProvenanceSnapshot,
)
from app.shared.schemas.common_schemas import (
    StrictSchemaModel,
    described_field,
    schema_list_default,
)


class OperationalRuntimeProvenanceResponse(StrictSchemaModel):
    """Build and native-extension identity observed by the running process."""

    checked: Annotated[
        bool,
        described_field("Whether runtime provenance was evaluated for this snapshot."),
    ]
    environment: Annotated[
        str,
        described_field(
            "Application environment associated with the runtime snapshot."
        ),
    ]
    runtime_revision: Annotated[
        str | None,
        described_field("Source revision baked into the running application image."),
    ] = None
    expected_revision: Annotated[
        str | None,
        described_field("Deployment revision expected by the runtime environment."),
    ] = None
    build_timestamp: Annotated[
        str | None,
        described_field("Build timestamp baked into the running application image."),
    ] = None
    native_revision: Annotated[
        str | None,
        described_field("Source revision baked into the loaded Rust extension."),
    ] = None
    native_package_version: Annotated[
        str | None,
        described_field("Package version reported by the loaded Rust extension."),
    ] = None
    native_build_profile: Annotated[
        str | None,
        described_field("Cargo build profile reported by the loaded Rust extension."),
    ] = None
    native_contract_version: Annotated[
        int | None,
        described_field(
            "Python/Rust compute contract version reported by native code."
        ),
    ] = None
    feature_authority_schema_version: Annotated[
        int | None,
        described_field(
            "Feature authority registry schema version reported by native code."
        ),
    ] = None
    verified: Annotated[
        bool,
        described_field(
            "Whether runtime, deployment, and native revisions are verified."
        ),
    ]
    drift_detected: Annotated[
        bool,
        described_field("Whether application runtime drift was explicitly detected."),
    ]
    native_aligned: Annotated[
        bool,
        described_field(
            "Whether loaded native code is aligned with the runtime revision."
        ),
    ]
    warnings: Annotated[
        list[str],
        described_field("Runtime provenance warnings for this readiness snapshot."),
    ] = schema_list_default()

    @classmethod
    def from_entity(
        cls,
        snapshot: OperationalRuntimeProvenanceSnapshot,
    ) -> OperationalRuntimeProvenanceResponse:
        """Map an internal runtime provenance snapshot to the HTTP contract.

        Args:
            snapshot: Internal runtime-provenance read model.

        Returns:
            Strict runtime-provenance response schema.
        """
        return cls(
            checked=snapshot.checked,
            environment=snapshot.environment,
            runtime_revision=snapshot.runtime_revision,
            expected_revision=snapshot.expected_revision,
            build_timestamp=snapshot.build_timestamp,
            native_revision=snapshot.native_revision,
            native_package_version=snapshot.native_package_version,
            native_build_profile=snapshot.native_build_profile,
            native_contract_version=snapshot.native_contract_version,
            feature_authority_schema_version=snapshot.feature_authority_schema_version,
            verified=snapshot.verified,
            drift_detected=snapshot.drift_detected,
            native_aligned=snapshot.native_aligned,
            warnings=list(snapshot.warnings),
        )


class OperationalRetrievalCanaryResultResponse(StrictSchemaModel):
    """One real retrieval-lane readiness result."""

    strategy: Annotated[
        RagStrategy,
        described_field("Retrieval strategy exercised by this readiness canary."),
    ]
    ok: Annotated[
        bool,
        described_field(
            "Whether this retrieval lane completed without fallback or failure."
        ),
    ]
    effective_strategy: Annotated[
        RagStrategy | None,
        described_field("Effective strategy returned by the normal retrieval path."),
    ] = None
    match_count: Annotated[
        int,
        described_field("Number of matches returned by the readiness canary.", ge=0),
    ]
    context_pack_built: Annotated[
        bool,
        described_field("Whether normal Context Pack construction completed."),
    ]
    failure_code: Annotated[
        str | None,
        described_field("Sanitized failure code for this retrieval canary."),
    ] = None
    warnings: Annotated[
        list[str],
        described_field("Warnings returned by the normal retrieval path."),
    ] = schema_list_default()

    @classmethod
    def from_entity(
        cls,
        result: OperationalRetrievalCanaryResult,
    ) -> OperationalRetrievalCanaryResultResponse:
        """Map one internal retrieval canary result to the HTTP contract.

        Args:
            result: Internal per-strategy canary result.

        Returns:
            Strict retrieval-canary result response schema.
        """
        return cls(
            strategy=result.strategy,
            ok=result.ok,
            effective_strategy=result.effective_strategy,
            match_count=result.match_count,
            context_pack_built=result.context_pack_built,
            failure_code=result.failure_code,
            warnings=list(result.warnings),
        )


class OperationalRetrievalCanarySnapshotResponse(StrictSchemaModel):
    """Bounded FTS, vector, and hybrid retrieval path health."""

    checked: Annotated[
        bool,
        described_field("Whether real retrieval canaries were executed."),
    ]
    query: Annotated[
        str,
        described_field("Bounded query used by the retrieval readiness canaries."),
    ]
    limit: Annotated[
        int,
        described_field("Result limit used by each retrieval readiness canary.", ge=3),
    ]
    healthy: Annotated[
        bool,
        described_field("Whether all required retrieval lanes completed successfully."),
    ]
    fts: Annotated[
        OperationalRetrievalCanaryResultResponse,
        described_field("FTS-only real-search readiness result."),
    ]
    vector: Annotated[
        OperationalRetrievalCanaryResultResponse,
        described_field("Vector-only real-search readiness result."),
    ]
    hybrid: Annotated[
        OperationalRetrievalCanaryResultResponse,
        described_field("Hybrid real-search readiness result."),
    ]

    @classmethod
    def from_entity(
        cls,
        snapshot: OperationalRetrievalCanarySnapshot,
    ) -> OperationalRetrievalCanarySnapshotResponse:
        """Map the internal retrieval canary snapshot to the HTTP contract.

        Args:
            snapshot: Internal aggregate retrieval-canary snapshot.

        Returns:
            Strict aggregate retrieval-canary response schema.
        """
        return cls(
            checked=snapshot.checked,
            query=snapshot.query,
            limit=snapshot.limit,
            healthy=snapshot.healthy,
            fts=OperationalRetrievalCanaryResultResponse.from_entity(snapshot.fts),
            vector=OperationalRetrievalCanaryResultResponse.from_entity(
                snapshot.vector
            ),
            hybrid=OperationalRetrievalCanaryResultResponse.from_entity(
                snapshot.hybrid
            ),
        )


class ContextProjectionIntegrityFailureResponse(StrictSchemaModel):
    """Aggregated projection failure count exposed by operational readiness."""

    code: Annotated[str, described_field("Machine-readable projection failure code.")]
    count: Annotated[int, described_field("Number of failures with this code.", ge=1)]

    @classmethod
    def from_entity(
        cls,
        failure: ContextProjectionIntegrityFailure,
    ) -> ContextProjectionIntegrityFailureResponse:
        """Map one internal projection failure aggregate to the HTTP contract.

        Args:
            failure: Internal projection failure aggregate.

        Returns:
            Strict projection failure response schema.
        """
        return cls(code=failure.code, count=failure.count)


class ContextProjectionIntegritySnapshotResponse(StrictSchemaModel):
    """Persisted full Obsidian-to-Context projection validation state."""

    checked: Annotated[
        bool, described_field("Whether projection integrity was evaluated.")
    ]
    available: Annotated[
        bool,
        described_field("Whether a persisted full projection scan is available."),
    ]
    healthy: Annotated[
        bool,
        described_field("Whether the persisted projection scan is current and clean."),
    ]
    source_revision: Annotated[
        str | None,
        described_field("Indexed-note revision validated by the persisted full scan."),
    ] = None
    current_source_revision: Annotated[
        str | None,
        described_field("Current indexed-note revision observed by readiness."),
    ] = None
    scanned_count: Annotated[
        int, described_field("Notes scanned by the full projection check.", ge=0)
    ]
    valid_count: Annotated[
        int, described_field("Notes that projected successfully.", ge=0)
    ]
    invalid_count: Annotated[
        int, described_field("Notes that failed Context projection.", ge=0)
    ]
    stale: Annotated[
        bool,
        described_field("Whether age or source revision makes this snapshot stale."),
    ]
    checked_at: Annotated[
        str | None,
        described_field("ISO-8601 time of the persisted full projection scan."),
    ] = None
    failures: Annotated[
        list[ContextProjectionIntegrityFailureResponse],
        described_field("Aggregated machine-readable projection failure counts."),
    ] = schema_list_default()

    @classmethod
    def from_entity(
        cls,
        snapshot: ContextProjectionIntegritySnapshot,
    ) -> ContextProjectionIntegritySnapshotResponse:
        """Map projection integrity state to the HTTP contract.

        Args:
            snapshot: Internal projection-integrity snapshot.

        Returns:
            Strict projection-integrity response schema.
        """
        return cls(
            checked=snapshot.checked,
            available=snapshot.available,
            healthy=snapshot.healthy,
            source_revision=snapshot.source_revision,
            current_source_revision=snapshot.current_source_revision,
            scanned_count=snapshot.scanned_count,
            valid_count=snapshot.valid_count,
            invalid_count=snapshot.invalid_count,
            stale=snapshot.stale,
            checked_at=None
            if snapshot.checked_at is None
            else snapshot.checked_at.isoformat(),
            failures=[
                ContextProjectionIntegrityFailureResponse.from_entity(failure)
                for failure in snapshot.failures
            ],
        )
