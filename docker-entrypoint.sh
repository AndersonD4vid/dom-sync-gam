#!/usr/bin/env bash
set -euo pipefail

echo "[entrypoint] Starting Redis in background..."
redis-server /app/redis.conf &
REDIS_PID=$!

RETRIES=0
MAX_RETRIES=15
until redis-cli -h 127.0.0.1 ping 2>/dev/null | grep -q PONG; do
    RETRIES=$((RETRIES + 1))
    if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then
        echo "[entrypoint] ERROR: Redis failed to start after ${MAX_RETRIES}s"
        exit 1
    fi
    echo "[entrypoint] Waiting for Redis... (${RETRIES}/${MAX_RETRIES})"
    sleep 1
done

echo "[entrypoint] Redis is ready (PID: ${REDIS_PID})"

cleanup() {
    echo "[entrypoint] Shutting down Redis..."
    redis-cli -h 127.0.0.1 shutdown nosave 2>/dev/null || true
    wait "$REDIS_PID" 2>/dev/null || true
    echo "[entrypoint] Cleanup complete"
}
trap cleanup SIGTERM SIGINT EXIT

echo "[entrypoint] Executing: $*"
exec "$@"
