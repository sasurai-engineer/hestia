#!/usr/bin/env python3
"""First-load JavaScript budget.

A page that takes ten seconds on a phone in a basement utility room is a
page that does not exist at 11pm. This gate holds every route's first-load
JavaScript — the chunks a browser must fetch before React hydrates — under
a fixed gzip budget, computed from the build's own manifest rather than a
framework's summary table, so the number is the wire truth.

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


def gzipped_size(path: Path) -> int:
    """The size that actually crosses the wire, not the size on disk."""
    return len(gzip.compress(path.read_bytes(), compresslevel=6))


def route_sizes(next_dir: Path) -> dict[str, int]:
    """Map each app route to the gzipped bytes of its first-load JS.

    ``app-build-manifest.json`` lists, per route, every asset the route
    needs on first load — shared framework chunks included, which is the
    point: a shared chunk that bloats bloats every route.
    """
    manifest_path = next_dir / "app-build-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    sizes: dict[str, int] = {}
    cache: dict[str, int] = {}
    for route, assets in manifest["pages"].items():
        total = 0
        for asset in assets:
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
    over: list[str] = []
    for route, size in sorted(route_sizes(next_dir).items()):
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
