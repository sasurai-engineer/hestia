# 0001 — Toolchain pins

**Status:** accepted · 2026-08-24

## Versions are resolved, not pinned

Selection moved to [`sasurai_assemble`](../../../sasurai_assemble), a
constraint-based provisioner for the whole workspace. Hestia declares floors
with reasons; the resolver installs the newest release satisfying every
project's floors, keg-only, so nothing global is relinked. `scripts/env.sh`
now only puts the result on PATH and holds no version numbers of its own.

Node 20 was too old — Stryker 10 requires `>=22`, and pnpm 11 requires
`>=22.13`. The resolver settles on `node@24`: `>=22` permits Node 26, but a
recorded ceiling holds the workspace on the LTS line until Node 26 is promoted
in October 2026. That ceiling carries a review date and expires on its own.

## pnpm 11 and the supply-chain policy

pnpm 11 enforces `minimumReleaseAge`, refusing dependencies published within a
configured window — set to 24 hours in `pnpm-workspace.yaml`. A release that
was compromised at publish time cannot be consumed before anyone notices.

The consequence is deliberate: dependency ranges must be wide enough that a
matured version exists. `^26.3.0` on a package released this morning will not
install. That is the policy working, not failing — widen the range rather than
relaxing the window.

## TypeScript is held at 6.x

TypeScript **7.0.2 is the native Go port** and removes legacy compiler APIs.
Both `ts.parseConfigFileTextToJson` and `ts.readConfigFile` are gone, and
Stryker's sandbox preprocessor calls the first of them:

```
TypeError: ts.parseConfigFileTextToJson is not a function
    at TSConfigPreprocessor.rewriteTSConfigFile
```

The mutation gate is not negotiable, so TypeScript pins to **6.0.3**, the last
release carrying the full API. Renovate is configured with
`allowedVersions: "<7.0.0"` so it cannot drift back. Revisit when stryker-js
ships TypeScript 7 support — the native compiler is materially faster and worth
returning to.

## Stryker plugins are registered explicitly

`stryker.config.json` names `@stryker-mutator/vitest-runner` in `plugins`.
Stryker's default glob discovery does not traverse pnpm's symlinked
`node_modules` from inside its sandbox, and fails with
`Cannot find TestRunner plugin "vitest"`.
