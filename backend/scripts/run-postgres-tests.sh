#!/usr/bin/env bash
set -euo pipefail

POSTGRES_IMAGE="${ALEXANDRIA_CI_POSTGRES_IMAGE:-pgvector/pgvector:pg17}"
POSTGRES_USER="alexandria_ci"
POSTGRES_PASSWORD="alexandria_ci"
POSTGRES_DB="alexandria_ci"
CONTAINER_NAME="heterarchy-alexandria-ci-postgres-${PPID}-$$"

: "${PYTHONPYCACHEPREFIX:=${XDG_CACHE_HOME:-$HOME/.cache}/heterarchy-alexandria/pycache}"
export PYTHONPYCACHEPREFIX

log() {
  printf '[postgres-tests] %s\n' "$*"
}

cleanup() {
  if docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    log "Stopping temporary PostgreSQL container."
    docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

log "Starting temporary PostgreSQL container from ${POSTGRES_IMAGE}."
docker run --detach --rm \
  --name "${CONTAINER_NAME}" \
  --env "POSTGRES_USER=${POSTGRES_USER}" \
  --env "POSTGRES_PASSWORD=${POSTGRES_PASSWORD}" \
  --env "POSTGRES_DB=${POSTGRES_DB}" \
  --publish 127.0.0.1::5432 \
  "${POSTGRES_IMAGE}" >/dev/null

log "Waiting for PostgreSQL readiness (timeout: 60s)."
ready=false
wait_started=${SECONDS}
for attempt in $(seq 1 60); do
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
  if [ "${attempt}" -eq 1 ] || [ $((attempt % 5)) -eq 0 ]; then
    log "PostgreSQL is still starting... ${attempt}/60s"
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

log "PostgreSQL ready in $((SECONDS - wait_started))s on 127.0.0.1:${postgres_port}."
export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${postgres_port}/${POSTGRES_DB}"

log "Starting pytest; dots show completed tests."
set +e
PYTHONUNBUFFERED=1 uv run --no-editable pytest -q --durations=10 "$@"
pytest_status=$?
set -e

if [ "${pytest_status}" -eq 0 ]; then
  log "pytest completed successfully."
else
  log "pytest failed with exit status ${pytest_status}."
fi
exit "${pytest_status}"
