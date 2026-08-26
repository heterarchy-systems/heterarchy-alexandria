"""Context Vault enum contracts."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum


class ContextKind(StrEnum):
    """Kinds of durable context stored by agents and humans."""

    HANDOFF = "HANDOFF"
    DECISION = "DECISION"
    BUG_ROOT_CAUSE = "BUG_ROOT_CAUSE"
    PLAN = "PLAN"
    COMPACT = "COMPACT"
    RESEARCH = "RESEARCH"
    USAGE = "USAGE"
    MEMORY = "MEMORY"


class MemoryFunction(StrEnum):
    """Functional role a durable memory serves during recall."""

    FACTUAL = "FACTUAL"
    EXPERIENTIAL = "EXPERIENTIAL"
    PROCEDURAL = "PROCEDURAL"


class ContextSourceType(StrEnum):
    """Source category for a captured context."""

    AGENT = "AGENT"
    USER = "USER"
    SYSTEM = "SYSTEM"
    IMPORTED = "IMPORTED"


class ContextScope(StrEnum):
    """Recall-routing scope for durable memory."""

    GLOBAL = "GLOBAL"
    PROJECT = "PROJECT"
    AGENT = "AGENT"
    SESSION = "SESSION"
    USER = "USER"


class ContextImportance(StrEnum):
    """Importance level used for recall ranking and filtering."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ContextStorageStatus(StrEnum):
    """Context lint/save statuses returned by the harness."""

    SAVED = "SAVED"
    SAVED_WITH_WARNINGS = "SAVED_WITH_WARNINGS"
    REDACTED_AND_SAVED = "REDACTED_AND_SAVED"
    BLOCKED_SECRET_RISK = "BLOCKED_SECRET_RISK"
    PENDING_REVIEW = "PENDING_REVIEW"

    @classmethod
    def default_recall_values(cls) -> tuple[str, ...]:
        """Return persisted Context statuses eligible for default recall.

        Returns:
            Persisted storage statuses included in ordinary recall.
        """
        return (
            cls.SAVED.value,
            cls.SAVED_WITH_WARNINGS.value,
            cls.REDACTED_AND_SAVED.value,
        )


class ContextRecallLifecycleStatus(StrEnum):
    """Lifecycle states selectable at the Context recall boundary."""

    CURRENT = "CURRENT"
    ACTIVE = "ACTIVE"
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    REVIEWED = "REVIEWED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"
    ERROR = "ERROR"
    SAVED = "SAVED"
    SAVED_WITH_WARNINGS = "SAVED_WITH_WARNINGS"
    REDACTED_AND_SAVED = "REDACTED_AND_SAVED"

    @classmethod
    def default_recall_values(cls) -> tuple[ContextRecallLifecycleStatus, ...]:
        """Return lifecycle states visible to ordinary recall.

        Returns:
            Lifecycle states included when no administrative filter is supplied.
        """
        return (
            cls.CURRENT,
            cls.ACTIVE,
            cls.SAVED,
            cls.SAVED_WITH_WARNINGS,
            cls.REDACTED_AND_SAVED,
        )

    @classmethod
    def context_storage_values(
        cls,
        statuses: Sequence[ContextRecallLifecycleStatus] | None,
    ) -> tuple[str, ...]:
        """Map recall lifecycle states to persisted Context storage statuses.

        Args:
            statuses: Explicit lifecycle selections, or None for defaults.

        Returns:
            Compatible persisted Context storage status values.
        """
        selected = statuses or list(cls.default_recall_values())
        storage_values: list[str] = []
        if cls.CURRENT in selected or cls.ACTIVE in selected:
            storage_values.extend(ContextStorageStatus.default_recall_values())
        persisted_values = frozenset(item.value for item in ContextStorageStatus)
        storage_values.extend(
            status.value for status in selected if status.value in persisted_values
        )
        return tuple(dict.fromkeys(storage_values))

    @classmethod
    def obsidian_values(
        cls,
        statuses: Sequence[ContextRecallLifecycleStatus] | None,
    ) -> tuple[str, ...]:
        """Map recall lifecycle states to normalized Obsidian status values.

        Args:
            statuses: Explicit lifecycle selections, or None for defaults.

        Returns:
            Normalized Obsidian lifecycle values.
        """
        selected = statuses or list(cls.default_recall_values())
        values: list[str] = []
        if any(
            status
            in {
                cls.SAVED,
                cls.SAVED_WITH_WARNINGS,
                cls.REDACTED_AND_SAVED,
            }
            for status in selected
        ):
            values.extend((cls.CURRENT.value.lower(), cls.ACTIVE.value.lower()))
        values.extend(
            status.value.lower()
            for status in selected
            if status
            not in {
                cls.SAVED,
                cls.SAVED_WITH_WARNINGS,
                cls.REDACTED_AND_SAVED,
            }
        )
        return tuple(dict.fromkeys(values))


class ContextContentFormat(StrEnum):
    """Supported context content formats."""

    MARKDOWN = "MARKDOWN"
    TEXT = "TEXT"


class ContextAccessActorType(StrEnum):
    """Actor categories for Context Vault access events."""

    UI = "UI"
    AGENT = "AGENT"
    LIBRARIAN = "LIBRARIAN"
    SYSTEM = "SYSTEM"


class ContextAccessMethod(StrEnum):
    """How a Context Vault entry was accessed."""

    DETAIL_VIEW = "DETAIL_VIEW"
    RECALL = "RECALL"
    RAG_SEARCH = "RAG_SEARCH"
    MCP_TOOL = "MCP_TOOL"


class RagStrategy(StrEnum):
    """Context retrieval strategies exposed by RAG search."""

    AUTO = "AUTO"
    FTS_ONLY = "FTS_ONLY"
    VECTOR_ONLY = "VECTOR_ONLY"
    HYBRID = "HYBRID"

    @classmethod
    def fixed(cls) -> tuple[RagStrategy, ...]:
        """Return only directly executable fixed retrieval lanes.

        Returns:
            Stable fixed-lane order used by benchmarks and readiness tests.
        """
        return (cls.FTS_ONLY, cls.VECTOR_ONLY, cls.HYBRID)


class ContextRetrievalIntent(StrEnum):
    """Deterministic query intents emitted by the adaptive retrieval planner."""

    EXACT_OR_TITLE = "EXACT_OR_TITLE"
    SEMANTIC_PARAPHRASE = "SEMANTIC_PARAPHRASE"
    TEMPORAL_CURRENT_STATE = "TEMPORAL_CURRENT_STATE"
    EXPERIENTIAL = "EXPERIENTIAL"
    PROCEDURAL = "PROCEDURAL"
    GRAPH_ORIENTED = "GRAPH_ORIENTED"
    MIXED = "MIXED"


class ContextRetrievalFusionProfile(StrEnum):
    """Versioned fusion profiles selected by Python retrieval policy."""

    NONE = "NONE"
    RECIPROCAL_RANK_V1 = "RECIPROCAL_RANK_V1"


class ContextGraphSignalType(StrEnum):
    """Optional graph evidence categories attached after primary recall."""

    GRAPH_PROXIMITY = "graph_proximity"
    IMPACT_ANALYSIS = "impact_analysis"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    SUPERSEDES_CANDIDATE = "supersedes_candidate"
    LINEAGE = "lineage"
    RESUME_PATH = "resume_path"


class ContextGraphDirection(StrEnum):
    """Direction of graph evidence relative to the recalled Context."""

    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


class RagHealthState(StrEnum):
    """Health states for retriever dependencies."""

    HEALTHY = "HEALTHY"
    REINDEX_REQUIRED = "REINDEX_REQUIRED"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"
