#!/usr/bin/env bash
set -euo pipefail

POSTGRES_IMAGE="${ALEXANDRIA_CI_POSTGRES_IMAGE:-pgvector/pgvector:pg17}"
POSTGRES_USER="alexandria_ci"
POSTGRES_PASSWORD="alexandria_ci"
POSTGRES_DB="alexandria_ci"
CONTAINER_NAME="heterarchy-alexandria-ci-postgres-${PPID}-$$"

cleanup() {
  docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker run --detach --rm \
  --name "${CONTAINER_NAME}" \
  --env "POSTGRES_USER=${POSTGRES_USER}" \
  --env "POSTGRES_PASSWORD=${POSTGRES_PASSWORD}" \
  --env "POSTGRES_DB=${POSTGRES_DB}" \
  --publish 127.0.0.1::5432 \
  "${POSTGRES_IMAGE}" >/dev/null

ready=false
for _ in $(seq 1 60); do
  if docker exec "${CONTAINER_NAME}" \
    pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
    ready=true
    break
  fi
  if [ "$(docker inspect --format '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null || true)" != "true" ]; then
    docker logs "${CONTAINER_NAME}" >&2 || true
    echo "Temporary PostgreSQL container exited before becoming ready." >&2
    exit 1
  fi
  sleep 1
done

if [ "${ready}" != "true" ]; then
  docker logs "${CONTAINER_NAME}" >&2 || true
  echo "Temporary PostgreSQL container did not become ready." >&2
  exit 1
fi

port_mapping="$(docker port "${CONTAINER_NAME}" 5432/tcp | head -n 1)"
postgres_port="${port_mapping##*:}"
if [ -z "${postgres_port}" ]; then
  echo "Could not resolve the temporary PostgreSQL host port." >&2
  exit 1
fi

export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${postgres_port}/${POSTGRES_DB}"
uv run --no-editable pytest "$@"
