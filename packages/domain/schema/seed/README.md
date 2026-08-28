# Seed packs

Seeds are data, not structure: the rows that make the jurisdiction engine
answer questions instead of holding them (ADR 0003 — jurisdiction is data).

## Numbering

| Range | Contents |
|---|---|
| `899_federal.sql` | The federal tier: the root jurisdiction row and rules that apply identically in all fifty states. Sorts before every pack; every pack may assume it is installed and nothing else. |
| `900–949` | State packs, one file per state: `9NN_jurisdictions_xx.sql`. |
| `950+` | Demo data and corrections. |

The migration runner (`scripts/migrate.py`) discovers seeds by glob — a new
pack file is picked up with zero code changes.

## What a state pack contains

1. **Jurisdiction rows** — the state (FIPS), plus the counties and
   municipalities in the owner footprint.
2. **Rule rows**, every one cited and effective-dated:
   - `assessment_appeal`: `appeal.window.calendar` (a registry key naming the
     window builder), `appeal.form`, `appeal.conference_required` (explicitly
     `false` where none), `appeal.instructions` (what the sweep prints).
   - `assessment_ratio`, landlord-tenant rows (statewide act or adoption map,
     whatever the state's structure), `income_tax` (state and, where real,
     municipal rows), `depreciation_conformity` incl. `conformity_kind`.
3. **Calendar registry entries** iff the state's window fits no existing
   builder — one pure function in `packages/engines/src/deadlines.ts` and one
   in `services/api/hestia_api/calendar.py`, each with two externally
   verified anchor dates. A key may be seeded at ANY level, not just the
   state: Tennessee's Shelby County convenes a month before the rest of the
   state, so `seed/907` puts `us-tn.shelby-county-board` on the county row
   and depth-first chain resolution prefers it. Give a deviation its own key
   rather than parameterising one builder — two callers whose authorities
   differ are two rules, and a single function pretending otherwise cannot
   cite either honestly.
4. **A pack test** — `tests/packs/xx.sql`, the Newport-vs-Campbell pattern:
   the chain resolves through `jurisdiction_chain()`, the calendar key /
   ratio / conformity discriminator resolve to the seeded values, and at
   least one assertion contrasts this pack against an already-installed one.
5. **Fixture rows** iff the pack adds conformity arithmetic, generated on the
   Python side per the differential discipline.

A figure not yet professionally confirmed carries `— CONFIRM WITH <STATE>
CPA` in its citation, and nothing downstream may present it as settled.

## Deterministic UUIDs

Each pack owns the block `a0000000-00FF-4000-8000-…` where `FF` is the state
FIPS code (Ohio = `0039`). Kentucky's original `a0000000-0000-…` block is
grandfathered. The federal row is `a0000000-0000-4000-8000-000000000001`.

## Applied-once discipline

The runner records a checksum per file and treats edits to applied files as
loud conflicts. **Corrections ship as new numbered files; never edit an
applied one.** (Documented exception: the 2026-08-25 pre-production
restructure that split `899_federal.sql` out of the Kentucky pack — every
database was reset and remigrated; if you hold an older local database, reset
it: `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` then re-run
`scripts/migrate.py --include-seeds`.)
