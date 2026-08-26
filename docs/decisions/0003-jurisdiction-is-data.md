# ADR 0003 — Jurisdiction is data, never a fork

Date: 2026-08-25 · Status: accepted

## Context

Hestia is a 50-state platform. Its first portfolio sits in Newport, Kentucky,
so Kentucky was seeded first — and during that work, Kentucky-specific behavior
leaked from *data* into *code*: the deadline sweep filtered `WHERE state = 'KY'`,
the KRS 133.045 inspection window existed only as KY-named functions, and the
KY §179 conformity numbers were baked as constants in two engines while the
authoritative rows sat in seed data. Left alone, that pattern ossifies into a
one-state product.

## Decision

**State-specific behavior lives in data and registries, never in dispatch
logic.** Concretely:

1. **Rules live in `jurisdiction_rules`** — cited, effective-dated, resolved
   through `jurisdiction_chain()` (most specific body wins, newest effective
   rule, superseded rows excluded).
2. **Calendars live in a code registry keyed by data.** A rule row
   (`domain = 'assessment_appeal'`, `code = 'appeal.window.calendar'`,
   `value_text = 'us-ky.open-inspection'`) names which registered window
   builder governs. Builders are small, anchor-tested, and twin-implemented
   (TypeScript and Python). There is deliberately **no date-rule DSL**
   interpreted from database text: a DSL cannot meet the mutation bar and its
   two interpreters would drift.
3. **A state is a pack**: one seed file `seed/9NN_jurisdictions_xx.sql`
   (+ a module migration iff it needs new enum vocabulary), one pack test
   `tests/packs/xx.sql`, registry entries iff no existing builder fits its
   calendars, fixture rows iff it adds conformity arithmetic. Definition of
   done for the architecture: a state whose calendars fit existing builders
   is **one seed file + one pack test — zero `.ts`/`.py` edits**.
4. **State literals are legal in exactly four places**: seed packs
   (`packages/domain/schema/seed/`), registry entries and their anchor tests,
   test fixture data, and prose (comments, docs, citations). Never in
   dispatch logic, shared type or field names, or SQL predicates.
   `scripts/check_state_literals.sh` enforces this in CI.
5. **Coverage over silence.** Where a property's jurisdiction chain has no
   loaded rule (or a rule names an unregistered calendar key), the sweep
   emits *no* deadline and a typed gap (`no_state_jurisdiction`,
   `no_rule_for_domain`, `calendar_key_unregistered`, `ambiguous_resolution`),
   and `GET /coverage/jurisdictions` reports known/unknown per rule domain.
   The platform does not alert on guesses — and does not hide what it does
   not know.

## Conventions

- **Pack numbering**: `899_federal.sql` (shared, sorts before every pack) ·
  `900–949` state packs · `950+` demo/correction seeds.
- **Deterministic UUIDs**: each pack owns the block
  `a0000000-00FF-4000-8000-............` where `FF` is the state FIPS code
  (Ohio = 39). Kentucky's original `a0000000-0000-…` block is grandfathered.
- **Seed files are applied-once**: the migration runner records checksums and
  treats edits as loud conflicts. Corrections ship as new numbered files.
  (The one-time restructure that split 899 out of the Kentucky file happened
  pre-production, with every database reset-and-remigrated.)
- **Unconfirmed figures carry it in the citation**: `— CONFIRM WITH <STATE>
  CPA`, the discipline the Kentucky pack established.
- **Anti-drift pins**: each pack's test asserts its seeded values; shared
  engine fixtures pin both languages' constants; calendar anchors pin both
  registry twins. Three copies of a number are acceptable only because CI
  fails when any copy moves alone.

## Consequences

- Adding a state is a data exercise reviewable by that state's professional.
- The registry (not a per-state module) is the only code that grows with
  novel calendar shapes, and it grows by one pure function per language.
- `rule_domain` stays an enum (typo-proof, coverage-report-enumerable); the
  cost is an `ALTER TYPE … ADD VALUE` module when a pack needs new
  vocabulary — accepted, since packs already ship migrations when needed.
- The KY-named exports (`kentuckySection179Limit`, `kyOpenInspectionWindow`,
  `pva_conference`) survive as pack-sanctioned wrappers and a permanent enum
  member; new code prefers the generic seams.
