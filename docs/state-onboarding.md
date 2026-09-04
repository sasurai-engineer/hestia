# State onboarding — the playbook

How a new state enters the platform. This is the process the third and fourth
states actually followed, written down so the fifth is cheaper than the
fourth — which is the tracked promise of ADR 0003's cost curve. A state is
added **when a door is** (a real property, a real address): depth-per-address,
never breadth-per-map. Each new address pays for its own research.

The worked examples throughout are Tennessee (seed/907 — the expensive state,
which bought two new shapes) and Texas (seed/909 — the cheap state, which fit
existing ones).

## 0. Predict, in writing, before researching

State which appeal-window shape you expect (computed / published / absent) and
why, in the coordination log, before opening a single source. Score the call
when the sources answer. The point is not the score — it is that an examined
assumption cannot ship the way an unexamined one can, and the Tennessee
lesson is exactly that: the "obvious" August 1 deadline was 36 days late for
Nashville, in the direction that waives the owner's appeal.

*Texas: predicted computed (s.41.44 sets May 15 by statute), confirmed.*

## 1. Research against primary sources, then try to kill the findings

- Statutes by section, from the state's own compilation (or a verifiable
  mirror when the official site resists automation — record which, and when
  verified). County and city facts from the county's and city's own pages.
- Every figure gets a citation it can be checked against. A figure that
  cannot be professionally confirmed yet ships with `— CONFIRM WITH <STATE>
  CPA/COUNSEL` **in the citation**, so nothing downstream can present it as
  settled.
- Before the pack merges, run an adversarial pass: independent refuters, one
  per slice of the pack, each instructed to REFUTE the seeded values against
  primary sources — with special attention to errors in the fatal direction
  (a date later than the law's, a boundary flipped, a cap outliving its
  sunset, an obligation said not to exist).

## 2. Pick the window shape by asking what actually determines the date

| The deadline is… | Shape | The pack carries | Code cost |
|---|---|---|---|
| a function of the calendar | **computed** | `appeal.window.calendar` naming a registry key | one pure builder per twin + anchors, iff no existing builder fits |
| an administrative decision somebody makes and revises | **published** | dated `opens_on`/`closes_on` rows, effective_from-paired, effective_to-bounded, plus `appeal.window.source` | none |
| not yet sourced | **absent** | `appeal.window.source` alone — a named gap | none |

Two hard-won rules ride on this table:

- **Never anchor a statutory window to a notice.** If the statute's later leg
  depends on a notice that is conditional (Texas s.25.19: unchanged value, no
  notice), emit the date the owner can rely on WITHOUT the notice and treat
  the notice-relative extension as per-parcel data entered when one arrives.
- **Never average two authorities into one builder.** Two callers whose
  sources differ are two rules; a builder that cannot cite one authority
  honestly is two builders, or it is data.

A published window carries its expiry consequence: every dated row is bounded
by `effective_to`, so each January the sweep reports
`window_awaiting_publication` — citing the county's own last row — until the
county publishes. That alarm is the mechanism; entering the new date each
year is the operational duty the pack hands the owner honestly.

## 3. Seed grammar (the rows every pack answers)

The full contract lives in `seed/README.md`; the checklist form:

- **Jurisdictions**: state (FIPS block `a0000000-00FF-…`), plus the counties
  and municipalities the doors are actually in — and every jurisdiction the
  act's own binding logic requires (Tennessee needed all seventeen covered
  counties, because the act binds by county and a missing county hands a
  landlord someone else's law).
- **Where a rule sits is a legal claim.** Statewide law on the state row;
  adoption- or population-gated law on the rows that carry the act, with the
  state carrying only the RULE FOR CHOOSING (`ltl.applies_by`), so an
  unplaceable property gets a gap, never a guess.
- **Absences are findings.** "No individual income tax", "no deposit
  interest", "no return deadline exists", "the homestead cap never applies to
  a rental" — each is a seeded row with a citation, because "no such duty"
  and "not loaded" must never look alike.
- **Self-terminating law terminates itself in data.** A statute with its own
  sunset ships with `effective_to` equal to that sunset (Texas s.23.231(k)),
  so the year after cannot silently inherit it; an extension is a NEW row
  citing the extending act.
- **Boundaries carry their direction in words.** "FOUR OR FEWER units — a
  four-plex QUALIFIES" survives a reader; `4` does not. The pack test pins
  the words.
- **Same answers, different routes, different citations.** When two states
  agree (Tennessee and Texas both answer "none" to income tax), the citations
  must not be interchangeable — one is a repeal, one is a constitution — and
  the pack test asserts they differ.

## 4. Pack test (`tests/packs/xx.sql`)

Read-only, runs in `verify-schema.sh` against the fully seeded database.
Assert at minimum:

1. The chain walks four levels from a door to the federal root.
2. **The cross-regime contrast**: one query shape against every installed
   state, all answers distinct in the way the law actually is (Texas: three
   computed keys plus Tennessee's deliberate NULL).
3. The shape holds in both directions (a computed state carries no published
   rows; a published state names no key).
4. The traps this state's research uncovered, each pinned in the words that
   make them unambiguous — boundary directions, sunsets resolved by as_of
   query, the notice-anchoring refusal, the filing that survives a threshold.
5. Citation hygiene: no empty citations, no section signs (`s.NN`, always —
   the sign does not survive every terminal this text will pass through).

## 5. Registry twins (only for a new computed calendar)

One pure builder per language — `packages/engines/src/deadlines.ts` and
`services/api/hestia_api/calendar.py` — same key, same anchors:

- Keys are timeless function identities (`us-xx.slug`). A statutory change is
  a NEW key behind a new effective-dated rule row, never an edit.
- Two externally verified anchors minimum, one of which exercises the
  weekend/holiday roll (Texas: 2026-05-15 Friday stands, 2027-05-15 Saturday
  rolls to Monday May 17).
- Emitted dates err early, never late — an unmodelled holiday extension makes
  the true deadline later than ours, never earlier.
- The mutation gate is not optional: the TS builder lands at 100% killed or
  it does not land.

## 6. Gates before the PR

`verify-schema.sh` (pack test green, restore check green) ·
`check_state_literals.sh` clean · full API suite at 100% line+branch ·
`pnpm verify` green including mutation · the adversarial refutation pass
from step 1 resolved — every WRONG fixed, every SUSPECT either fixed or
downgraded with a primary source.

## 7. Record the cost

In the PR: what the state cost (files, lines, service-code lines), which
shapes it used, and whether it discovered a new one. This is the
cost-per-authority curve ADR 0003 tracks — the claim that authority #21 costs
less than authority #1 is only checkable if every pack writes its price down.

| State | Shapes | Cost | Service code |
|---|---|---|---|
| TN (seed/907) | bought *published* + *absent* + county-population adoption | 1,245 lines / 18 files | 214 lines |
| TX (seed/909) | fit *computed*, statewide act | 2 data files + registry twins | 0 lines |
