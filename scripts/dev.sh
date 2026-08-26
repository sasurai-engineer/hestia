#!/usr/bin/env bash
# The whole stack, one command: PostgreSQL (disposable container) -> schema +
# seeds via the real migration runner -> the API on :8000 -> the web app on
# :3000. Ctrl-C tears everything down.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER="${HESTIA_DEV_CONTAINER:-hestia-dev-db}"
IMAGE="${HESTIA_POSTGRES_IMAGE:-docker.io/library/postgres:17-alpine}"
PORT="${HESTIA_DEV_DB_PORT:-15432}"
API_PORT="${HESTIA_DEV_API_PORT:-8000}"

ENGINE="$(command -v podman || command -v docker)" \
  || { echo "need podman or docker" >&2; exit 2; }

say() { printf '\033[1;33m[hestia]\033[0m %s\n' "$*"; }

# Preflight: a port already in use produces a confusing half-up stack, so
# refuse loudly with the fix instead.
for port in 3000 "$API_PORT" "$PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    say "port $port is already in use:"
    lsof -nP -iTCP:"$port" -sTCP:LISTEN | tail -n +2 | awk '{print "         " $1 " (pid " $2 ")"}'
    say "stop that process (or a previous dev.sh: pkill -f 'next dev'; pkill -f uvicorn) and rerun"
    exit 2
  fi
done
command -v uv >/dev/null || { say "uv is not on PATH — run: eval \"\$(~/workspace/sasurai_assemble/assemble shellenv)\""; exit 2; }
command -v pnpm >/dev/null || { say "pnpm is not on PATH — run: eval \"\$(~/workspace/sasurai_assemble/assemble shellenv)\""; exit 2; }

cleanup() {
  say "shutting down"
  [ -n "${API_PID:-}" ] && kill "$API_PID" 2>/dev/null || true
  [ -n "${WEB_PID:-}" ] && kill "$WEB_PID" 2>/dev/null || true
  "$ENGINE" rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

say "starting postgres ($CONTAINER on :$PORT)"
"$ENGINE" rm -f "$CONTAINER" >/dev/null 2>&1 || true
"$ENGINE" run -d --name "$CONTAINER" \
  -e POSTGRES_PASSWORD=hestia-dev `# config-audit: allow — throwaway dev container` \
  -e POSTGRES_DB=hestia \
  -p "$PORT:5432" "$IMAGE" >/dev/null
for _ in $(seq 1 60); do
  "$ENGINE" exec "$CONTAINER" pg_isready -U postgres >/dev/null 2>&1 && break
  sleep 1
done

say "applying schema and seeds"
python3 "$ROOT/scripts/migrate.py" --include-seeds \
  --psql "$ENGINE exec -i $CONTAINER psql -U postgres -d hestia"

export HESTIA_DATABASE_URL="postgresql://postgres:hestia-dev@127.0.0.1:$PORT/hestia"
say "starting the API on :$API_PORT"
(cd "$ROOT/services/api" && exec uv run uvicorn hestia_api.app:app \
  --port "$API_PORT" --reload) &
API_PID=$!

say "starting the web app on :3000"
(cd "$ROOT/apps/web" && exec pnpm dev) &
WEB_PID=$!

say "up — open http://localhost:3000 (API at http://localhost:$API_PORT/docs)"
wait "$API_PID" "$WEB_PID"
