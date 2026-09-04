# ADR 0003 — Jurisdiction is data, never a fork

Date: 2026-08-25 · Status: accepted · **Amended 2026-09-04**

> **Amendment note.** The original claimed a definition of done — "a state is
> one seed file + one pack test, zero `.ts`/`.py` edits" — that Tennessee
> falsified: it cost 1,245 lines across 18 files, including 214 lines of new
> sweep and deposit behavior, because it introduced a shape no earlier state
> had needed. The claim below is rewritten as the cost model the four-state
> record actually supports: **packs carry facts and rules; code carries
> arithmetic and shapes; a state pays for a new shape exactly once, and a
> state that fits existing shapes costs data plus registry entries only.**
> Nothing else in the decision changed, and the ratchet and gap discipline
> stand as written.

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
3. **A state is a pack, and the pack schema is a compiler.** Facts and rules
   compile to data (one seed file `seed/9NN_jurisdictions_xx.sql`, one pack
   test `tests/packs/xx.sql`); arithmetic and **shapes** compile to code. A
   *shape* is a structural way the law can answer a question — an appeal
   window that is computed, published, or absent; a landlord-tenant act that
   binds statewide, by municipal adoption, or by county population; a
   conformity regime that is frozen, addback-recovered, or none. The honest
   cost model, measured:

   - **A state that introduces a new shape pays for the shape once.**
     Tennessee bought the published window, the named-absence gap, and the
     third adoption pattern: 1,245 lines across 18 files, 214 of them new
     service behavior. That price was the shape's, not Tennessee's — every
     later state gets it free.
   - **A state that fits existing shapes costs data plus registry entries.**
     Texas, the fourth state, fit the computed shape: one seed file, one pack
     test, one pure builder per language twin with anchors — 138 lines of
     sanctioned registry code, **zero service-code changes**.

   The tracked metric is the **cost-per-authority curve**: each pack records
   what it cost, and a later authority must cost less to bank than an earlier
   one. A new state that unexpectedly costs service code is either a genuine
   new shape (name it, document it in `seed/README.md`) or a leak (stop).
4. **State literals are legal in exactly four places**: seed packs
   (`packages/domain/schema/seed/`), registry entries and their anchor tests,
   test fixture data, and prose (comments, docs, citations). Never in
   dispatch logic, shared type or field names, or SQL predicates.
   `scripts/check_state_literals.sh` enforces this in CI — and the leak it
   guards against is broader than literals: a governance *fact* embedded in
   dispatch logic is the same failure wearing no state name.
5. **Coverage over silence.** Where a property's jurisdiction chain has no
   loaded rule (or a rule names an unregistered calendar key), the sweep
   emits *no* deadline and a typed gap (`no_state_jurisdiction`,
   `no_rule_for_domain`, `calendar_key_unregistered`, `ambiguous_resolution`,
   `window_not_published`, `window_awaiting_publication`),
   and `GET /coverage/jurisdictions` reports known/unknown per rule domain.
   The platform does not alert on guesses — and does not hide what it does
   not know.

## Conventions

- **Pack numbering**: `899_federal.sql` (shared, sorts before every pack) ·
  `900–949` state packs · `950+` demo/correction seeds.
- **Deterministic UUIDs**: each pack owns the block
  `a0000000-00FF-4000-8000-............` where `FF` is the state FIPS code
  (Ohio = 39, Tennessee = 47, Texas = 48). Kentucky's original
  `a0000000-0000-…` block is grandfathered.
- **Seed files are applied-once**: the migration runner records checksums and
  treats edits as loud conflicts. Corrections ship as new numbered files.
  (The one-time restructure that split 899 out of the Kentucky file happened
  pre-production, with every database reset-and-remigrated.)
- **Unconfirmed figures carry it in the citation**: `— CONFIRM WITH <STATE>
  CPA`, the discipline the Kentucky pack established.
- **Predictions are stated before research and scored after**: before a pack
  is researched, the researcher states which shape they expect and why, in
  the coordination log, and scores the call when the primary sources answer.
  Texas established the practice (predicted computed, confirmed against
  s.41.44 and s.1.06). A wrong prediction is cheap; an unexamined assumption
  ships a Tennessee-style wrong deadline.
- **Anti-drift pins**: each pack's test asserts its seeded values; shared
  engine fixtures pin both languages' constants; calendar anchors pin both
  registry twins. Three copies of a number are acceptable only because CI
  fails when any copy moves alone.

## Consequences

- Adding a state is a data exercise reviewable by that state's professional —
  *bounded by the shape inventory*: the reviewer of a pack that fits existing
  shapes reviews rows and citations, never behavior.
- The registry (not a per-state module) is the only code that grows with
  novel calendar shapes, and it grows by one pure function per language.
- The shape inventory itself is an asset with a falsifiable trend: if the
  fifth and sixth states keep discovering new shapes, the model is wrong and
  this ADR must be revisited; the four-state record (two shapes discovered by
  state one and two, one by state three, none by state four) says the
  inventory converges.
- `rule_domain` stays an enum (typo-proof, coverage-report-enumerable); the
  cost is an `ALTER TYPE … ADD VALUE` module when a pack needs new
  vocabulary — accepted, since packs already ship migrations when needed.
- The KY-named exports (`kentuckySection179Limit`, `kyOpenInspectionWindow`,
  `pva_conference`) survive as pack-sanctioned wrappers and a permanent enum
  member; new code prefers the generic seams.
