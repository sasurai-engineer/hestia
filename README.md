# Hestia

**An owner's operating platform for real property.**

Every tool in this category is a ledger with charts on top. Hestia is a decision
engine with a ledger underneath. It does not ask what you spent last month; it
answers what you should do, by when, and what it costs you if you are wrong.

It opens with a filled dossier, never a blank form.

---

## The rule

> **The engines compute. The model explains. The model never does arithmetic.**

Depreciation schedules, IRR, recapture splits, coinsurance penalties and component
survival curves are deterministic code with exhaustive tests. The language model
retrieves, extracts, reasons about jurisdiction and narrates — it *calls* the
engines and interprets what they return. Every figure it reports carries its
inputs, its authority, and its counterfactual.

This is the only way "every claim grounded" survives contact with a language model.

## Quick start

```bash
source scripts/env.sh     # put the provisioned toolchain on PATH
pnpm install
pnpm run verify           # lint · typecheck · coverage · mutation
```

Toolchain versions are not decided here. `scripts/env.sh` delegates to
[`sasurai_assemble`](../sasurai_assemble), which resolves the newest release
satisfying every project's constraints and installs it keg-only, so upgrading
Node for Hestia never relinks the Node that Metis and the Oracle repos build
against. On a fresh machine:

```bash
cd ~/workspace/sasurai_assemble && ./bootstrap.sh && ./assemble apply
```

Run `assemble explain node` to see which project asks for what, and why.

## Layout

```
packages/
  domain/       types, branded Money, schemas — the single source of truth
  engines/      exact-decimal math: amortization, IRR/NPV, dual-book MACRS,
                recapture, rent EV, coinsurance, hold/sell. Client-side capable.
  design/       Hestia design tokens, primitives, charts
  api-client/   generated from OpenAPI, typed end to end
services/
  api/          FastAPI — the typed contract (OpenAPI), correlated requests,
                same-transaction audit writes, the deadline sweep, and the
                dossier orchestrator (address -> geocode -> jurisdiction ->
                hazard -> inference -> sweep, one transaction). Tested
                against a real migrated PostgreSQL only — never a mock.
  ingest/       provider adapters (Census, FEMA — mappers proven against
                live-recorded responses) + the onboarding inference engine
  sim/          Weibull Monte Carlo capital forecast + the Python reference
                implementations that generate the engines' shared fixtures
apps/
  web/          Next.js — the primary analytical surface: portfolio, dossier,
                transactions, calendar, coverage, on Hestia's own livery
                ("Hearth & Survey", token-tested — the product carries no
                consultancy branding, and a test enforces it).
                Typed client generated from the committed OpenAPI contract.
  ios/          Expo / React Native — native companion
  desktop/      Tauri 2 — wraps the web build
corpus/
  hestia-datasets/  staged training curriculum + jurisdiction RAG specs
```

**Why the engines are split across two languages.** Dragging an exit date on the
timeline must recompute tax consequence with no round trip, so amortization, IRR,
depreciation and recapture live in TypeScript and run in the client. Monte Carlo
survival simulation and optimization stay in Python where numpy and scipy belong.
Both sides are held to the same standard and cross-validated to the cent against
shared fixtures.

## Run it

```bash
./scripts/dev.sh    # postgres (podman) + migrations + seeds + API :8000 + web :3000
```

Open http://localhost:3000, add a property, press **Assemble dossier** — the
platform geocodes it, resolves the governing bodies, probes FEMA, infers the
component inventory and era defects, and puts the deadlines on the calendar.

## Standards

Enforced from commit one, because a standard retrofitted is a standard abandoned.

| Gate | Tool | Threshold |
|---|---|---|
| Lint & format | Biome | zero findings |
| Types | TypeScript (strict + `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`) | zero errors |
| Coverage | Vitest / pytest | **100% line + branch** |
| Mutation score | Stryker / mutmut | **≥ 90%** |
| Invariants | fast-check / Hypothesis | property-based |
| SAST | CodeQL + Semgrep (`--severity=ERROR --error`) | zero high, and it can fail |
| Dependencies | Renovate + pnpm audit + OSV + Trivy (`exit-code: 1`) | nightly CVE sweep, blocking |
| Config drift & leaked credentials | `scripts/config_audit.py` (18 self-tests) | zero findings; values never echoed |
| Schema | migration runner + real PostgreSQL, constraints proven by name | 79 assertions + per-pack proofs + proven restore |
| Engines ↔ Python differential | shared fixtures, two independent implementations | agreement to the cent |
| Supply chain | Syft SBOM · Sigstore cosign · SLSA L3 | verified per release |

Coverage is the floor, not the bar. 100% coverage with weak assertions is theater;
the mutation score is what proves the tests actually bite.

**Money is never a float.** `NUMERIC` in Postgres, `Decimal` in Python, `decimal.js`
behind a branded `Money` type in TypeScript. The type system refuses to add a rate
to a dollar.

**Renters are `residents`.** In this stack `tenant` means *workspace*. The collision
is settled permanently in favour of clarity.

## A standing caveat

Hestia computes, cites and surfaces deadlines. It is engineering scaffolding for a
qualified professional's review — not a substitute for one, and nothing it produces
is tax or legal advice.

---

*Developed by The Aletheia Institute. The product is Hestia's alone.*
