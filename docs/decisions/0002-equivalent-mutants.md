# 0002 — The mutation gate, and what survives it

**Status:** accepted · 2026-08-24, revised 2026-08-25

The mutation gate breaks below 90%. `@hestia/domain` scores **91.69%** across
`money.ts`, `rate.ts`, `numeric.ts` and `errors.ts`, at 100% line and branch
coverage, over 173 tests.

## Why the gate exists

The first run of this module scored **86.63% with 100% line and branch
coverage**. Forty-six mutants survived a fully covered file. Closing them
surfaced two real simplifications and one real gap in the rounding tests —
`HalfDown` agreed with `HalfEven` on every case asserted, so deleting its entire
`case` arm changed nothing at all.

Two later review rounds made the same point again from the other direction: a
guard can be fully covered and still not bite. `isRate` was covered, and
accepted a forged object literal. `assertCurrency` was covered, and the render
path it was written to protect never called it. Coverage says a line ran.
Mutation says the assertion around it mattered.

## What survives, by kind

The residue is dominated by mutations that cannot change observable behaviour:

- **Sign comparisons** — `< 0n` → `<= 0n` on a magnitude test. Negating zero
  gives zero, so both branches agree wherever these appear.
- **Preallocation** — `new Array<bigint>(n)` → `[]`. A capacity hint, not a
  semantic.
- **Cache internals** — whether a bounded memo stores an entry is invisible to
  every caller by construction; the cache exists to be transparent.
- **Message wording** — the subject labels inside error strings that no
  assertion pins. Where a label carries diagnostic value (`left operand` versus
  `right operand`, `fraction numerator` versus `fraction denominator`) it *is*
  pinned, because telling a caller which input was wrong is the whole value of
  the message.

## Policy

Do not chase the residue. If the score falls below 90%, or a survivor appears in
a guard, a boundary, or a branch that decides a monetary value, the tests have a
real gap — fix the tests, not the threshold.

Regenerate the survivor breakdown from `reports/mutation/report.json`; it moves
with every change to the module and a hand-copied table in this file would go
stale, which is the failure mode the first revision of this document actually
demonstrated by contradicting itself about the count.

## The engines package

`@hestia/engines` runs the same gate and scores **98.91%** at 100% line and
branch coverage, over 67 tests plus the Python differential suite. Its five
survivors are equivalent by argument, not by fatigue:

- `npv` — `t === 0` short-circuit: period zero discounted by `(1+r)^0` is
  multiplication by exactly one, so removing the branch changes nothing.
- `irr` — the mid-loop `sign === 0` early return: without it, bisection simply
  converges deeper into the same zero-NPV plateau; every contractual assertion
  (tolerance, NPV-at-solution zero) still holds by design.
- `depreciation` — `>=` vs `>` at the declining-balance switch: the two methods
  are value-equal at the tie, and straight line stays ahead afterwards either
  way.
- `holdsell` — the retired-note `break`: further iterations add zero interest
  and zero principal, so the break is an optimisation with no observable
  effect.
- `rent` — comparing the best candidate against itself on the first loop pass:
  neither strictly-better nor tied-but-smaller can be true reflexively.

The `switched` flag and a `!strictlyBetter` guard that produced three more
survivors were removed instead of documented — redundant state is where
equivalent mutants breed.

## @hestia/design — 96.97% (32/33 killed)

The design package's one mutable module is the WCAG contrast arithmetic the
livery's accessibility claims are recomputed from. Its single survivor is
equivalent by argument:

- `contrast` — `c <= 0.04045` vs `c < 0.04045` at the sRGB linearization
  threshold: the boundary would need a channel of exactly `0.04045 × 255 =
  10.31475`, and 8-bit channels are integers, so no representable color can
  distinguish the two comparisons.

## @hestia/design charts — 97.92% (five survivors, all argued)

The chart geometry joins the engines' bar. Its survivors:

- `ticks` — the three `niceNum` round-mode boundaries (`fraction < 1.5`,
  `< 3`, `< 7` vs `<=`): the rounding pass receives a nice span (1, 2, or
  5 × 10^k) divided by an integer tick count, and no such quotient's
  mantissa can land exactly on 1.5, 3, or 7 — the boundaries are
  unreachable through the public API.
- `ticks` — the half-step loop tolerance (`<=` vs `<` against
  `last + step/2`): accumulated tick values approximate multiples of the
  step; exact equality with a half-step offset cannot occur.
- `contrast` — the sRGB linearization threshold, documented above.
