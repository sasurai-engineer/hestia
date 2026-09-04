# Seed packs

Seeds are data, not structure: the rows that make the jurisdiction engine
answer questions instead of holding them (ADR 0003 — jurisdiction is data).

## Numbering

| Range | Contents |
|---|---|
| `899_federal.sql` | The federal tier: the root jurisdiction row and rules that apply identically in all fifty states. Sorts before every pack; every pack may assume it is installed and nothing else. |
| `900–949` | State packs, one file per state (`9NN_jurisdictions_xx.sql`), and the registry seeds that are data rather than structure: `905` and `908` are `extraction_field_specs` rows for a document kind, `906` names a deposit-interest formula builder. A registry seed is not a pack and needs no pack test. |
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
3. **An appeal window, in one of three shapes.** Pick by asking what
   actually determines the date:
   - *Computed.* The deadline is a function of the year, so the pack names a
     registry key in `appeal.window.calendar` and the two twins
     (`packages/engines/src/deadlines.ts` and
     `services/api/hestia_api/calendar.py`) each carry one pure builder with
     two externally verified anchor dates. Kentucky, Ohio and Texas are this shape.
     Keys are timeless function identities: a statutory change is a NEW key
     behind a new effective-dated rule row, never an edit to a builder.
   - *Published.* The deadline is an administrative decision somebody makes
     and revises, so no function can be right. The pack carries the dates as
     data — `appeal.window.opens_on` and `appeal.window.closes_on`, matched
     into one window by a shared `effective_from`, each bounded by
     `effective_to` so a date cannot outlive its year — plus
     `appeal.window.source` on the state row saying where the date comes
     from. Tennessee is this shape: its county boards convene on a statutory
     date but adjourn when they choose, and adjournment is the deadline
     (`seed/907`).
   - *Neither yet.* Seed `appeal.window.source` alone. The sweep reports
     `window_not_published`, which tells a reader where to go looking
     instead of implying the state has no appeal law.

   A rule may be seeded at ANY level, not just the state — depth-first chain
   resolution prefers the nearer row, so a county that differs from its state
   simply carries its own. Never parameterise one builder across two
   authorities: two callers whose sources differ are two rules, and a single
   function pretending otherwise cannot cite either honestly.
4. **A pack test** — `tests/packs/xx.sql`, the Newport-vs-Campbell pattern:
   the chain resolves through `jurisdiction_chain()`, the calendar key /
   ratio / conformity discriminator resolve to the seeded values, and at
   least one assertion contrasts this pack against an already-installed one.
5. **Fixture rows** iff the pack adds conformity arithmetic, generated on the
   Python side per the differential discipline.

A figure not yet professionally confirmed carries `— CONFIRM WITH <STATE>
CPA` in its citation, and nothing downstream may present it as settled.

## Correcting a rule that turns out to be wrong

A pack is applied-once and its bytes may never change, so a wrong rule is
never edited. It is replaced, and which of the two shapes you want depends on
whether the old text was ever right.

**A CORRECTION** — the rule was wrong from the start. Insert the replacement
carrying the **same** `jurisdiction_id`, `domain`, `code` and `effective_from`
as the row it replaces, then point the old row's `superseded_by` at the new
row's id. The old row stays in the table forever: a resolver excludes it, and
anyone asking what the pack said last March still gets an answer.

**AN AMENDMENT** — the rule was right and the law changed. Set `effective_to`
on the old row to the day the new rule starts, and insert the new rule with
that date as its `effective_from`. Both rows stay open; the effective window
decides which one resolves on any given date.

`seed/952_ohio_appeal_instructions_correction.sql` is the worked example of
the first shape, and it is a real one: Ohio's appeal instructions asserted a
filing window that ORC 5715.19(A) does not state. Read it before writing your
own.

Two things to know before you start:

- **The open-twin guard will catch a half-finished correction.**
  `tests/constraints.sql` fails the build if two OPEN rules ever share
  `(jurisdiction_id, domain, code, effective_from)`. That is exactly the state
  an insert-without-the-update leaves behind, which is why the two statements
  belong in one file and therefore one transaction.
- **A correction is scoped to its own code.** Superseding
  `appeal.instructions` must leave `appeal.window.calendar` untouched, and
  `services/api/tests/test_pack_corrections.py` asserts precisely that — a
  correction that quietly disturbed a neighbouring rule would be worse than
  the error it fixed.

Both mechanisms are exercised end to end against real Postgres in
`test_pack_corrections.py`: the sweep emits from the new rule, the coverage
report cites it, and the superseded row is proved to survive.

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
