"""Docker Compose topology, tuning, and process lifecycle contracts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = REPOSITORY_ROOT / "docker-compose.yml"
ENV_COMPOSE_PATH = REPOSITORY_ROOT / "env-compose.yml"
DOCKERFILE_PATH = REPOSITORY_ROOT / "backend" / "Dockerfile"
ROOT_MAKEFILE_PATH = REPOSITORY_ROOT / "Makefile"
PERFORMANCE_ENV_PATH = REPOSITORY_ROOT / "runtime-performance.env"
REDIS_START_PATH = REPOSITORY_ROOT / "scripts" / "redis-start.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_app_processes_extend_one_shared_env_compose_contract() -> None:
    """API and worker should share one explicit application runtime definition."""
    compose = _read(COMPOSE_PATH)
    shared = _read(ENV_COMPOSE_PATH)

    assert compose.count("      file: ./env-compose.yml\n") == 2
    assert compose.count("      service: alexandria-app-base\n") == 2
    assert "x-alexandria-app-base:" not in compose
    assert "x-alexandria-runtime-environment:" not in compose
    assert "      - ./.env\n" in shared
    assert "      - ./runtime-performance.env\n" in shared
    assert shared.index("      - ./.env\n") < shared.index(
        "      - ./runtime-performance.env\n"
    )
    assert "      SERVICE_OBSIDIAN_VAULT_PATH: /vault\n" in shared
    assert "      - ${ALEXANDRIA_HOST_OBSIDIAN_VAULT_PATH}:/vault\n" in shared
    assert "      - embedding-model-cache:/app/cache/embeddings\n" in shared
    assert "  embedding-model-cache:\n" in compose
    assert "fastembed-cache" not in compose
    assert "fastembed-cache" not in shared


def test_runtime_image_build_requires_and_bakes_one_source_revision() -> None:
    """Local images should fail closed without provenance and share one revision identity."""
    dockerfile = _read(DOCKERFILE_PATH)
    makefile = _read(ROOT_MAKEFILE_PATH)

    warm_build = dockerfile.index("RUN cargo build")
    seal_arg = dockerfile.index("ARG ALEXANDRIA_BUILD_REVISION", warm_build)
    seal_build = dockerfile.index('RUN case "${ALEXANDRIA_BUILD_REVISION}"', seal_arg)

    assert warm_build < seal_arg < seal_build
    assert "ALEXANDRIA_BUILD_REVISION must identify the built source tree" in dockerfile
    assert "SERVICE_RUNTIME_REVISION=${ALEXANDRIA_BUILD_REVISION}" in dockerfile
    assert (
        "SERVICE_RUNTIME_EXPECTED_REVISION=${ALEXANDRIA_BUILD_REVISION}" in dockerfile
    )
    assert (
        'ALEXANDRIA_BUILD_REVISION="${ALEXANDRIA_BUILD_REVISION}" cargo build'
        in dockerfile
    )
    assert "runtime_revision:" in makefile
    assert "runtime_rebuild:" in makefile
    assert (
        "docker compose build alexandria-backend alexandria-maintenance-worker"
        in makefile
    )
    assert "docker compose up -d --no-build --force-recreate" in makefile


def test_compose_execs_uvicorn_and_isolates_maintenance_work() -> None:
    """Signals reach Uvicorn while CPU-heavy maintenance stays off the API loop."""
    compose = _read(COMPOSE_PATH)
    worker_start = compose.index("  alexandria-maintenance-worker:")
    worker_end = compose.index("\n  alexandria-postgres:", worker_start)
    worker_service = compose[worker_start:worker_end]

    assert (
        "/app/.venv/bin/alembic upgrade head && exec /app/.venv/bin/uvicorn app.main:app"
        in compose
    )
    assert "--reload" not in compose
    assert (
        "      - /app/.venv/bin/python\n"
        "      - -m\n"
        "      - app.operations.workers.redis_maintenance_worker\n" in worker_service
    )
    assert "alexandria-backend:\n        condition: service_healthy" in worker_service
    assert "alexandria-redis:\n        condition: service_healthy" in worker_service


def test_runtime_tuning_is_explicit_and_separate_from_credentials() -> None:
    """Deterministic performance knobs should not be duplicated in Compose."""
    compose_sources = _read(COMPOSE_PATH) + _read(ENV_COMPOSE_PATH)
    performance = _read(PERFORMANCE_ENV_PATH)
    performance_owned_names = (
        "SERVICE_REDIS_OPERATIONAL_READINESS_TTL_SECONDS",
        "SERVICE_REDIS_GRAPH_STATUS_TTL_SECONDS",
        "SERVICE_REDIS_EMBEDDING_HEALTH_TTL_SECONDS",
        "SERVICE_RAG_EMBEDDING_CACHE_DIR",
        "SERVICE_RAG_EMBEDDING_THREADS",
        "SERVICE_RAG_MAINTENANCE_EMBEDDING_THREADS",
        "SERVICE_REDIS_MAINTENANCE_WORKER_CONCURRENCY",
        "SERVICE_REDIS_MAINTENANCE_BATCH_LIMIT",
        "SERVICE_REDIS_MAINTENANCE_MAX_ATTEMPTS",
        "SERVICE_REDIS_MAINTENANCE_RETRY_IDLE_SECONDS",
        "SERVICE_REDIS_MAINTENANCE_DEDUP_COOLDOWN_SECONDS",
        "ALEXANDRIA_REDIS_MAXMEMORY",
    )

    assert ":-" not in compose_sources
    assert "SERVICE_REDIS_URL=redis://alexandria-redis:6379/0\n" in performance
    assert "SERVICE_REDIS_URL" not in compose_sources
    for name in performance_owned_names:
        assert name not in compose_sources
        assert f"{name}=" in performance


def test_performance_profile_matches_the_measured_single_user_host() -> None:
    """The checked-in profile should preserve a bounded single-user CPU budget."""
    performance = _read(PERFORMANCE_ENV_PATH)

    assert "SERVICE_RAG_EMBEDDING_THREADS=4\n" in performance
    assert "SERVICE_RAG_MAINTENANCE_EMBEDDING_THREADS=8\n" in performance
    assert "SERVICE_REDIS_MAINTENANCE_WORKER_CONCURRENCY=1\n" in performance
    assert "SERVICE_REDIS_MAINTENANCE_BATCH_LIMIT=250\n" in performance
    assert "SERVICE_REDIS_MAINTENANCE_RETRY_IDLE_SECONDS=120\n" in performance
    assert "SERVICE_REDIS_MAINTENANCE_DEDUP_COOLDOWN_SECONDS=300\n" in performance


def test_compose_uses_postgres_as_the_runtime_database() -> None:
    """PostgreSQL should use explicit Alexandria-owned environment mappings."""
    compose = _read(COMPOSE_PATH)
    postgres_start = compose.index("  alexandria-postgres:")
    postgres_end = compose.index("\n  alexandria-redis:", postgres_start)
    postgres_service = compose[postgres_start:postgres_end]

    assert "image: pgvector/pgvector:pg17" in postgres_service
    assert "env_file:" not in postgres_service
    assert "DATABASE_URL:" not in compose
    assert 'POSTGRES_DB: "${ALEXANDRIA_POSTGRES_DB}"' in postgres_service
    assert 'POSTGRES_USER: "${ALEXANDRIA_POSTGRES_USER}"' in postgres_service
    assert 'POSTGRES_PASSWORD: "${ALEXANDRIA_POSTGRES_PASSWORD}"' in postgres_service
    assert "pg_isready" in postgres_service
    assert "          - postgres\n" in postgres_service
    assert "- postgres-data:/var/lib/postgresql/data" in postgres_service
    assert "  postgres-data:\n" in compose


def test_compose_runs_redis_as_a_bounded_queue_safe_store() -> None:
    """Redis should preserve Streams jobs without becoming canonical storage."""
    compose = _read(COMPOSE_PATH)
    script = _read(REDIS_START_PATH)
    redis_start = compose.index("  alexandria-redis:")
    redis_end = compose.index("\nvolumes:", redis_start)
    redis_service = compose[redis_start:redis_end]

    assert "image: redis:8.8.1-alpine" in redis_service
    assert "      - ./runtime-performance.env\n" in redis_service
    assert (
        'entrypoint: ["/bin/sh", "/usr/local/bin/alexandria-redis-start.sh"]'
        in redis_service
    )
    assert (
        "./scripts/redis-start.sh:/usr/local/bin/alexandria-redis-start.sh:ro"
        in redis_service
    )
    assert '--save ""' in script
    assert "--appendonly yes" in script
    assert "--appendfsync everysec" in script
    assert '--maxmemory "${ALEXANDRIA_REDIS_MAXMEMORY}"' in script
    assert "--maxmemory-policy noeviction" in script
    assert '["CMD", "redis-cli", "ping"]' in redis_service
    assert "- redis-data:/data" in redis_service
    assert "  redis-data:\n" in compose
    assert "6379:6379" not in redis_service


def test_redis_start_script_fails_closed_for_blank_memory_budget() -> None:
    """A blank Redis memory budget must fail before the image entrypoint runs."""
    env = {"PATH": os.environ["PATH"], "ALEXANDRIA_REDIS_MAXMEMORY": "   "}

    result = subprocess.run(
        ["/bin/sh", str(REDIS_START_PATH)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "ALEXANDRIA_REDIS_MAXMEMORY must not be blank" in result.stderr
