#!/usr/bin/env python3
"""First-load JavaScript budget.

A page that takes ten seconds on a phone in a basement utility room is a
page that does not exist at 11pm. This gate holds every route's first-load
JavaScript — the chunks a browser must fetch before React hydrates — under
a fixed gzip budget, computed from the build's own manifest rather than a
framework's summary table, so the number is the wire truth.

Two things this learned the hard way (#112). Next's per-route entries do
NOT include the chunks of the layouts that wrap them, so a route measured
on its own entry is measured without the code that ships on every page --
here, the command palette and the emergency dispatch overlay. And a gate
that only fails when a route is over budget will pass cheerfully when it
measured no routes at all, which is how a gate stops gating.

Runs against a completed ``next build``. Requires no running stack, no
network, and no third-party packages. Exit code 0 means every route is
under budget; 1 means at least one route is over, each named with its
figure.

    python3 scripts/check_bundle_budget.py [--app apps/web] [--budget-kb 180]
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

DEFAULT_BUDGET_KB = 180
# The app has fourteen page routes today; a build that yields almost none
# has failed in a way the per-route budget cannot see.
MIN_ROUTES = 5


def gzipped_size(path: Path) -> int:
    """The size that actually crosses the wire, not the size on disk."""
    return len(gzip.compress(path.read_bytes(), compresslevel=6))


def wrapping_layouts(route: str, keys: set[str]) -> list[str]:
    """Every layout key that wraps ``route``, outermost first.

    A route at ``/a/b/page`` is wrapped by ``/layout``, ``/a/layout`` and
    ``/a/b/layout`` — whichever the manifest actually holds. Next lists a
    layout's chunks only under its own key, never inside the routes it
    wraps, so a route measured without these is measured without the code
    that ships on every page under it.
    """
    segments = route.split("/")[1:-1]  # drop the leading "" and the trailing "page"
    prefixes = ["/layout"]
    for depth in range(len(segments)):
        prefixes.append("/" + "/".join(segments[: depth + 1]) + "/layout")
    return [p for p in prefixes if p in keys]


def route_sizes(next_dir: Path) -> dict[str, int]:
    """Map each app route to the gzipped bytes of its first-load JS.

    Each route's own assets plus the assets of every layout that wraps it —
    shared framework chunks included, which is the point: a shared chunk
    that bloats bloats every route. Layout keys are not reported as routes
    of their own; nobody navigates to a layout.
    """
    manifest_path = next_dir / "app-build-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    pages = manifest["pages"]
    keys = set(pages)
    sizes: dict[str, int] = {}
    cache: dict[str, int] = {}
    for route, assets in pages.items():
        if not route.endswith("/page"):
            continue
        wanted: list[str] = list(assets)
        for layout in wrapping_layouts(route, keys):
            wanted += pages[layout]
        total = 0
        for asset in dict.fromkeys(wanted):  # de-duplicated, order preserved
            if not asset.endswith(".js"):
                continue
            if asset not in cache:
                cache[asset] = gzipped_size(next_dir / asset)
            total += cache[asset]
        sizes[route] = total
    return sizes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", default="apps/web", help="app directory holding .next")
    parser.add_argument(
        "--min-routes",
        type=int,
        default=MIN_ROUTES,
        help="fail if fewer than this many routes were measured",
    )
    parser.add_argument(
        "--budget-kb",
        type=int,
        default=DEFAULT_BUDGET_KB,
        help="per-route first-load JS budget, gzipped kilobytes",
    )
    args = parser.parse_args(argv)

    next_dir = Path(args.app) / ".next"
    if not (next_dir / "app-build-manifest.json").exists():
        print(f"no build manifest under {next_dir} — run `pnpm run build` first")
        return 1

    budget = args.budget_kb * 1024
    sizes = route_sizes(next_dir)
    # A gate that passes when it measured nothing is not a gate. An empty
    # manifest, or one whose shape a Next upgrade changed under us, must be
    # a failure rather than a cheerful zero-route success.
    if len(sizes) < args.min_routes:
        print(
            f"measured {len(sizes)} route(s), expected at least {args.min_routes} — "
            "the manifest is empty or its shape changed; refusing to pass"
        )
        return 1

    over: list[str] = []
    for route, size in sorted(sizes.items()):
        verdict = "over budget" if size > budget else "ok"
        print(f"{route:42s} {size / 1024:8.1f} KB gz  {verdict}")
        if size > budget:
            over.append(route)

    if over:
        print(f"\n{len(over)} route(s) over the {args.budget_kb} KB first-load budget")
        return 1
    print(f"\nevery route under the {args.budget_kb} KB first-load budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
