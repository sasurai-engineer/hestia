#!/usr/bin/env bash
# ADR 0003's mechanical enforcement: state-specific behavior lives in data
# (seed packs) and registries, never in dispatch logic. This ratchet fails
# the build on any comparison of a state column/variable/subscript against a
# two-letter literal — the exact shape of the coupling (`WHERE state = 'KY'`)
# that once made the deadline sweep Kentucky-only — outside the sanctioned
# locations: seed packs, schema tests, and test suites.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Matches every comparison idiom the scanned languages actually use:
#   SQL         state = 'KY'          p.state='KY'
#   Python      state == "OH"         record["state"] == "OH"   row['state']=='TX'
#   TypeScript  state === 'KY'        property.state === "KY"
# `={1,3}` covers =, == and === ; the optional quote+bracket covers subscripts.
PATTERN="state[\"']?\]?[[:space:]]*={1,3}[[:space:]]*[\"'][A-Z]{2}[\"']"

SCAN_DIRS=(
  "$ROOT/packages/domain/schema"
  "$ROOT/packages/engines/src"
  "$ROOT/services/api/hestia_api"
  "$ROOT/services/ingest/hestia_ingest"
  "$ROOT/services/sim/hestia_sim"
  "$ROOT/scripts"
)

# A renamed tree silently dropping out of the scan would un-ratchet the
# ratchet — and grep's exit code cannot carry that signal, because BSD grep
# reports success whenever ANY match was found (and the sanctioned seed files
# always match). Existence is checked explicitly instead.
for dir in "${SCAN_DIRS[@]}"; do
  if [ ! -d "$dir" ]; then
    echo "state-literal ratchet: scanned tree is missing: $dir" >&2
    echo "update SCAN_DIRS in this script if the tree moved" >&2
    exit 2
  fi
done

set +e
FOUND="$(grep -RInE "$PATTERN" "${SCAN_DIRS[@]}" \
  --include='*.sql' --include='*.ts' --include='*.py' --include='*.sh')"
STATUS=$?
set -e
if [ "$STATUS" -gt 1 ]; then
  echo "state-literal ratchet: grep failed (exit $STATUS)" >&2
  exit "$STATUS"
fi

FOUND="$(printf '%s\n' "$FOUND" \
  | grep -v "/schema/seed/" \
  | grep -v "/schema/tests/" \
  | grep -v "\.test\.ts:" \
  | grep -v "check_state_literals.sh:" \
  || true)"

if [ -n "$FOUND" ]; then
  echo "state-literal dispatch found outside ADR-0003-sanctioned locations:" >&2
  printf '%s\n' "$FOUND" >&2
  echo "" >&2
  echo "States are data packs. Resolve through jurisdiction_chain() and" >&2
  echo "jurisdiction_rules, or register a calendar builder — never branch" >&2
  echo "on a state literal. See docs/decisions/0003-jurisdiction-is-data.md" >&2
  exit 1
fi
echo "state-literal ratchet: clean"
