#!/usr/bin/env bash
set -euo pipefail

image="redis:8.8.1-alpine"
container_name="alexandria-redis-maintenance-tests-$$-${RANDOM}"
network_name="alexandria-redis-maintenance-tests-$$-${RANDOM}"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! docker image inspect "$image" >/dev/null 2>&1; then
  docker pull "$image"
fi

cleanup() {
  docker rm -f "$container_name" >/dev/null 2>&1 || true
  docker network rm "$network_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

docker network create \
  --label com.heterarchy-alexandria.redis-maintenance-test=true \
  "$network_name" >/dev/null
docker run --detach \
  --name "$container_name" \
  --label com.heterarchy-alexandria.redis-maintenance-test=true \
  --network "$network_name" \
  --publish 127.0.0.1::6379 \
  "$image" \
  redis-server --save '' --appendonly no --protected-mode no >/dev/null

port="$(docker inspect --format '{{(index (index .NetworkSettings.Ports "6379/tcp") 0).HostPort}}' "$container_name")"
if [[ -z "$port" ]]; then
  printf '%s\n' 'The isolated Redis container did not publish a loopback port.' >&2
  exit 1
fi

ready=false
for _attempt in {1..50}; do
  if python3 - "$port" >/dev/null 2>&1 <<'PY'
import socket
import sys

with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=1) as connection:
    connection.sendall(b"*1\r\n$4\r\nPING\r\n")
    if connection.recv(32) != b"+PONG\r\n":
        raise SystemExit(1)
PY
  then
    ready=true
    break
  fi
  sleep 0.1
done
if [[ "$ready" != true ]]; then
  printf '%s\n' 'The isolated Redis 8.8.1 container did not become ready.' >&2
  docker logs "$container_name" >&2
  exit 1
fi

cd "$script_dir/../.."
REDIS_MAINTENANCE_TEST_URL="redis://127.0.0.1:${port}/0" \
  uv run --no-editable pytest -q \
    --confcutdir=tests/operations \
    tests/operations/test_redis_maintenance_execution_fences.py \
    tests/operations/test_redis_maintenance_job_queue.py \
    tests/operations/test_redis_maintenance_worker.py
