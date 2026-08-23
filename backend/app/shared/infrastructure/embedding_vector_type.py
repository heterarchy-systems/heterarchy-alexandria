"""PostgreSQL pgvector embedding storage type."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from pgvector.sqlalchemy import Vector
from sqlalchemy.engine import Dialect
from sqlalchemy.sql.type_api import TypeEngine
from sqlalchemy.types import TypeDecorator

from app.shared.types.embedding_types import (
    EMBEDDING_VECTOR_DIMENSIONS,
    EmbeddingVector,
    normalize_embedding_vector,
)


class EmbeddingVectorType(TypeDecorator[EmbeddingVector]):
    """Store fixed-dimension numeric vectors with PostgreSQL pgvector."""

    impl = Vector
    cache_ok = True

    def __init__(self, dimensions: int = EMBEDDING_VECTOR_DIMENSIONS) -> None:
        """Initialize a fixed-dimension embedding storage type.

        Args:
            dimensions: Required number of embedding values.
        """
        super().__init__()
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[EmbeddingVector]:
        """Return the PostgreSQL pgvector storage implementation.

        Args:
            dialect: SQLAlchemy dialect compiling the column.

        Returns:
            Dialect-specific storage implementation.
        """
        if dialect.name != "postgresql":
            raise ValueError("EmbeddingVectorType requires PostgreSQL/pgvector")
        return cast(
            TypeEngine[EmbeddingVector],
            dialect.type_descriptor(Vector(self.dimensions)),
        )

    def process_bind_param(
        self,
        value: EmbeddingVector | Sequence[float] | None,
        dialect: Dialect,
    ) -> EmbeddingVector | list[float] | str | None:
        """Normalize outbound values at the persistence boundary.

        Args:
            value: Numeric vector.
            dialect: SQLAlchemy dialect executing the bind.

        Returns:
            Native pgvector values.
        """
        if value is None:
            return None
        if dialect.name != "postgresql":
            raise ValueError("EmbeddingVectorType requires PostgreSQL/pgvector")
        normalized = normalize_embedding_vector(
            value,
            expected_dimensions=self.dimensions,
        )
        return list(normalized)

    def process_result_value(
        self,
        value: Sequence[float] | None,
        dialect: Dialect,
    ) -> EmbeddingVector | None:
        """Restore database values as immutable numeric vectors.

        Args:
            value: Driver-returned pgvector values.
            dialect: SQLAlchemy dialect that returned the value.

        Returns:
            Immutable vector or None for nullable columns.
        """
        if value is None:
            return None
        if dialect.name != "postgresql":
            raise ValueError("EmbeddingVectorType requires PostgreSQL/pgvector")
        return normalize_embedding_vector(
            value,
            expected_dimensions=self.dimensions,
        )
