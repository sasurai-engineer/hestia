#!/usr/bin/env bash
# Apply the schema to a real PostgreSQL and prove the constraints reject what
# they claim to reject.
#
# Two modes, chosen automatically:
#   - PGHOST set (CI, with a postgres service): use the local psql client.
#   - otherwise: start a throwaway container and exec psql inside it, so no
#     local PostgreSQL client is required.
set -euo pipefail

SCHEMA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../packages/domain/schema" && pwd)"
CONTAINER="${HESTIA_SCHEMA_CONTAINER:-hestia-schema-check}"
IMAGE="${HESTIA_POSTGRES_IMAGE:-docker.io/library/postgres:17-alpine}"
DB="${PGDATABASE:-hestia}"

say() { printf '  %s\n' "$*"; }

if [ -n "${PGHOST:-}" ]; then
  # ---- CI: a postgres service is already listening. -----------------------
  # Throwaway service container in CI; never a real credential.
  export PGPASSWORD="${PGPASSWORD:-postgres}"  # config-audit: allow
  PSQL=(psql -h "$PGHOST" -p "${PGPORT:-5432}" -U "${PGUSER:-postgres}" -d "$DB")
  PSQL_CMD="psql -h $PGHOST -p ${PGPORT:-5432} -U ${PGUSER:-postgres} -d $DB"
  run_sql() { "${PSQL[@]}" -q -v ON_ERROR_STOP=1 -f "$1"; }
  reset_db() { "${PSQL[@]}" -q -c 'DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;'; }
  say "using postgres at ${PGHOST}:${PGPORT:-5432}"
else
  # ---- Local: a disposable container. -------------------------------------
  ENGINE="$(command -v podman || command -v docker)" \
    || { echo "need podman or docker (or set PGHOST)" >&2; exit 2; }
  say "using $("$ENGINE" --version)"
  "$ENGINE" rm -f "$CONTAINER" >/dev/null 2>&1 || true
  "$ENGINE" run -d --name "$CONTAINER" \
    -e POSTGRES_PASSWORD=verify -e "POSTGRES_DB=$DB" \
    "$IMAGE" >/dev/null
  trap '"$ENGINE" rm -f "$CONTAINER" >/dev/null 2>&1 || true' EXIT

  say "waiting for postgres"
  for _ in $(seq 1 60); do
    if "$ENGINE" exec "$CONTAINER" psql -U postgres -d "$DB" -tAc 'select 1' >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  "$ENGINE" exec "$CONTAINER" psql -U postgres -d "$DB" -tAc 'select 1' >/dev/null \
    || { echo "postgres never became ready" >&2; exit 1; }
  "$ENGINE" exec "$CONTAINER" mkdir -p /schema
  for f in "$SCHEMA_DIR"/*.sql "$SCHEMA_DIR"/tests/*.sql "$SCHEMA_DIR"/tests/packs/*.sql; do
    "$ENGINE" cp "$f" "$CONTAINER:/schema/$(basename "$f")"
  done
  run_sql() { "$ENGINE" exec "$CONTAINER" psql -U postgres -d "$DB" -q -v ON_ERROR_STOP=1 -f "/schema/$(basename "$1")"; }
  PSQL_CMD="$ENGINE exec -i $CONTAINER psql -U postgres -d $DB"
  reset_db() { "$ENGINE" exec "$CONTAINER" psql -U postgres -d "$DB" -q -c 'DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;'; }
fi

# The manifest is hand-maintained, so it can silently omit a module -- and a
# module that never runs leaves CI green, because the tests only exercise what
# got created. Verified before anything is applied.
MISSING=""
for module in "$SCHEMA_DIR"/[0-9][0-9][0-9]_*.sql; do
  name="$(basename "$module")"
  case "$name" in 000_all.sql) continue ;; esac
  grep -qF "\\ir $name" "$SCHEMA_DIR/000_all.sql" || MISSING="$MISSING $name"
done
if [ -n "$MISSING" ]; then
  say "000_all.sql does not include:$MISSING"
  exit 1
fi

printf '\n'
say "applying schema via the migration runner"
reset_db >/dev/null
python3 "$(dirname "${BASH_SOURCE[0]}")/migrate.py" \
  --schema-dir "$SCHEMA_DIR" --include-seeds --psql "$PSQL_CMD"
say "schema and seeds applied"

# A second run must be a no-op: the runner's whole promise is that applying is
# idempotent and drift is loud.
SECOND="$(python3 "$(dirname "${BASH_SOURCE[0]}")/migrate.py" \
  --schema-dir "$SCHEMA_DIR" --include-seeds --psql "$PSQL_CMD")"
case "$SECOND" in
  *"up to date"*) say "second run: up to date (idempotent)" ;;
  *) say "second run was not a no-op:"; printf '%s\n' "$SECOND" >&2; exit 1 ;;
esac

printf '\n'
say "constraint tests"

# Capture rather than filter in a pipe. A `sed -n` that prints only matching
# lines also discards the psql ERROR that says which constraint regressed,
# leaving a failed CI job with a non-zero exit and no diagnostic.
OUTPUT="$(run_sql "$SCHEMA_DIR/tests/constraints.sql" 2>&1)" || {
  printf '\n'
  say "constraint tests FAILED"
  printf '%s\n' "$OUTPUT" >&2
  exit 1
}

printf '%s\n' "$OUTPUT" | sed -nE 's/^.*NOTICE: +(ok +.*)$/    \1/p'

# A run that asserted nothing must not report success. Without a floor, an
# empty or short-circuited test file prints "schema verified" just as loudly as
# a complete one.
ASSERTIONS="$(printf '%s\n' "$OUTPUT" | grep -c 'NOTICE: *ok ' || true)"
# `|| true` on both counts: grep -c exits 1 on a zero count and 2 on a missing
# file, and under `set -e` a bare assignment adopts that status -- killing the
# script with no message, right after it printed the section header, which
# reads exactly like a constraint regression.
MINIMUM="$(grep -cE '^ *(SELECT|PERFORM) assert_(rejected|accepted)\(' \
  "$SCHEMA_DIR/tests/constraints.sql" || true)"
: "${MINIMUM:=0}"
: "${ASSERTIONS:=0}"
say "$ASSERTIONS assertions ran"
if [ "$ASSERTIONS" -lt "$MINIMUM" ]; then
  say "expected at least $MINIMUM assertions; the test file did not run to completion"
  printf '%s\n' "$OUTPUT" >&2
  exit 1
fi

# Every state pack proves it answers the questions it exists to answer. A
# pack file that runs but asserts nothing must not pass, so each must print
# at least one ok.
printf '\n'
say "pack tests"
for pack in "$SCHEMA_DIR"/tests/packs/*.sql; do
  PACK_OUT="$(run_sql "$pack" 2>&1)" || {
    say "pack test FAILED: $(basename "$pack")"
    printf '%s\n' "$PACK_OUT" >&2
    exit 1
  }
  printf '%s\n' "$PACK_OUT" | sed -nE 's/^.*NOTICE: +(ok +.*)$/    \1/p'
  PACK_OK="$(printf '%s\n' "$PACK_OUT" | grep -c 'NOTICE: *ok ' || true)"
  : "${PACK_OK:=0}"
  if [ "$PACK_OK" -lt 1 ]; then
    say "pack test asserted nothing: $(basename "$pack")"
    printf '%s\n' "$PACK_OUT" >&2
    exit 1
  fi
  say "$(basename "$pack" .sql) pack: $PACK_OK checks"
done

printf '\n'
say "backup and restore"
HESTIA_SCHEMA_CONTAINER="$CONTAINER" "$(dirname "${BASH_SOURCE[0]}")/backup.sh" verify

printf '\n'
say "schema verified"
