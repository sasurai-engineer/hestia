#!/usr/bin/env bash
# Backup and PROVEN restore for the Hestia ledger.
#
# A backup that has never been restored is a hope, not a backup — so `verify`
# takes a dump, restores it into a scratch database, and compares object and
# row counts before saying anything comforting.
#
# Modes mirror verify-schema.sh: with PGHOST set, the local pg_dump/pg_restore
# clients speak to that server; otherwise the named container's own tools run
# via the engine.
set -euo pipefail

say() { printf '  %s\n' "$*"; }

MODE="${1:-verify}"
CONTAINER="${HESTIA_SCHEMA_CONTAINER:-hestia-schema-check}"
DB="${PGDATABASE:-hestia}"
SCRATCH="${DB}_restore_check"
OUT="${2:-/tmp/hestia-backup.dump}"

if [ -n "${PGHOST:-}" ]; then
  export PGPASSWORD="${PGPASSWORD:-postgres}"  # config-audit: allow
  PSQL=(psql -h "$PGHOST" -p "${PGPORT:-5432}" -U "${PGUSER:-postgres}")
  DUMP=(pg_dump -h "$PGHOST" -p "${PGPORT:-5432}" -U "${PGUSER:-postgres}")
  RESTORE=(pg_restore -h "$PGHOST" -p "${PGPORT:-5432}" -U "${PGUSER:-postgres}")
  copy_in() { :; }
else
  ENGINE="$(command -v podman || command -v docker)" \
    || { echo "need podman or docker (or set PGHOST)" >&2; exit 2; }
  PSQL=("$ENGINE" exec "$CONTAINER" psql -U postgres)
  DUMP=("$ENGINE" exec "$CONTAINER" pg_dump -U postgres)
  RESTORE=("$ENGINE" exec "$CONTAINER" pg_restore -U postgres)
fi

table_count() { "${PSQL[@]}" -d "$1" -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"; }
# Exact per-table counts as 'table|count' lines — pg_stat's n_live_tup is an
# estimate and a single spot-check table proves nothing about the other 40.
table_rows() { "${PSQL[@]}" -d "$1" -tAc \
  "SELECT string_agg(table_name || '|' || (xpath('/row/cnt/text()',
     query_to_xml('SELECT count(*) AS cnt FROM ' || quote_ident(table_name),
                  false, true, '')))[1]::text, E'\n' ORDER BY table_name)
   FROM information_schema.tables WHERE table_schema='public'"; }

case "$MODE" in
  backup)
    if [ -n "${PGHOST:-}" ]; then
      "${DUMP[@]}" -d "$DB" -Fc -f "$OUT"
    else
      "${DUMP[@]}" -d "$DB" -Fc > "$OUT"
    fi
    say "backup written: $OUT ($(wc -c < "$OUT" | tr -d ' ') bytes)"
    ;;
  verify)
    # Dump into the server-side filesystem (container mode) or locally.
    if [ -n "${PGHOST:-}" ]; then
      "${DUMP[@]}" -d "$DB" -Fc -f "$OUT"
      RESTORE_SRC="$OUT"
    else
      "$ENGINE" exec "$CONTAINER" pg_dump -U postgres -d "$DB" -Fc -f /tmp/backup.dump
      RESTORE_SRC=/tmp/backup.dump
    fi
    "${PSQL[@]}" -d postgres -q -c "DROP DATABASE IF EXISTS ${SCRATCH}"
    "${PSQL[@]}" -d postgres -q -c "CREATE DATABASE ${SCRATCH}"
    "${RESTORE[@]}" -d "$SCRATCH" --no-owner "$RESTORE_SRC"
    ORIG_TABLES="$(table_count "$DB")"; REST_TABLES="$(table_count "$SCRATCH")"
    ORIG_ROWS="$(table_rows "$DB")"; REST_ROWS="$(table_rows "$SCRATCH")"
    RULES="$("${PSQL[@]}" -d "$SCRATCH" -tAc 'SELECT count(*) FROM jurisdiction_rules')"
    "${PSQL[@]}" -d postgres -q -c "DROP DATABASE ${SCRATCH}"
    if [ "$ORIG_TABLES" != "$REST_TABLES" ] || [ "$ORIG_ROWS" != "$REST_ROWS" ]; then
      say "RESTORE MISMATCH: tables $ORIG_TABLES vs $REST_TABLES"
      diff <(printf '%s\n' "$ORIG_ROWS") <(printf '%s\n' "$REST_ROWS") >&2 || true
      exit 1
    fi
    say "restore verified: $ORIG_TABLES tables, every table's row count identical, $RULES seeded rules"
    ;;
  *)
    echo "usage: backup.sh [backup|verify] [outfile]" >&2; exit 2 ;;
esac
