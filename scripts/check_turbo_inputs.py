#!/usr/bin/env python3
"""Turbo's declared inputs must cover every directory its tasks actually read.

A task whose ``inputs`` omit a file it reads will replay a cached success
after that file changes -- a gate reporting a run that never happened. It
happened: ``apps/web`` keeps its whole suite in ``tests/``, ``packages/design``
keeps the livery laws there, and neither was hashed, so a broken law returned
"FULL TURBO" in 14ms.

This walks every workspace package, reads the globs its vitest config actually
includes, and asserts turbo hashes the directories those globs live in.

Runs against a checkout. No network, no running stack, no third-party packages.
Exit 0 means every test task hashes what it reads; 1 means a gate can lie.

    python3 scripts/check_turbo_inputs.py [--root .]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TEST_TASKS = ("test", "test:coverage", "test:mutation")
# The task reads these whether or not a glob names them.
ALWAYS_READ = {"fixtures"}


def top_dirs(globs: list[str]) -> set[str]:
    """The first path segment of each glob -- the directory turbo must hash."""
    return {g.split("/", 1)[0] for g in globs if "/" in g and not g.startswith("!")}


def vitest_includes(pkg: Path) -> list[str]:
    """The include globs a package's vitest config declares, if any."""
    for name in ("vitest.config.ts", "vitest.config.mts", "vitest.config.js"):
        cfg = pkg / name
        if not cfg.exists():
            continue
        match = re.search(r"include:\s*\[(.*?)\]", cfg.read_text(), re.S)
        if match:
            return re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))
        # No explicit include: vitest's default sweeps the whole package.
        return ["src/**", "tests/**", "test/**"]
    return []


def packages(root: Path) -> list[Path]:
    found: list[Path] = []
    for parent in ("packages", "apps", "services"):
        base = root / parent
        if base.is_dir():
            found += [p for p in sorted(base.iterdir()) if (p / "package.json").exists()]
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.root)

    turbo = json.loads((root / "turbo.json").read_text())
    tasks = turbo["tasks"]
    findings: list[str] = []

    for pkg in packages(root):
        includes = vitest_includes(pkg)
        if not includes:
            continue
        needed = {d for d in top_dirs(includes) if (pkg / d).is_dir()}
        needed |= {d for d in ALWAYS_READ if (pkg / d).is_dir()}
        for task in TEST_TASKS:
            spec = tasks.get(f"{pkg.name}#{task}") or tasks.get(task)
            if spec is None or "inputs" not in spec:
                continue  # no declared inputs: turbo hashes the package, which is safe
            hashed = top_dirs(spec["inputs"])
            for missing in sorted(needed - hashed):
                findings.append(
                    f"{pkg.as_posix()}: task '{task}' reads {missing}/ but does not hash it"
                )

    for finding in findings:
        print(finding)
    if findings:
        print(f"\n{len(findings)} task(s) can replay a pass they never ran")
        return 1
    print("every test task hashes the directories it reads")
    return 0


if __name__ == "__main__":
    sys.exit(main())
