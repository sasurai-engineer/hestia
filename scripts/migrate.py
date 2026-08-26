#!/usr/bin/env python3
"""The schema migration runner.

Forward-only, checksummed, and boring on purpose. Modules are the numbered
files in ``packages/domain/schema``; seeds are the numbered files in its
``seed/`` directory. Each is applied once, inside a single transaction, and
recorded in ``schema_migrations`` with the sha256 of the exact text applied —
so a module edited after the fact is a loud conflict, never a silent
divergence between the files and the database.

Stdlib only, and the SQL travels over stdin, so the same runner drives a local
psql, a CI service container, or ``podman exec`` without caring which.

    python3 scripts/migrate.py --psql "psql -h localhost -U postgres -d hestia"
    python3 scripts/migrate.py --psql "..." --include-seeds
    python3 scripts/migrate.py --psql "..." --plan   # show, change nothing
"""

from __future__ import annotations

import argparse
import hashlib
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SCHEMA_DIR = Path(__file__).resolve().parents[1] / "packages" / "domain" / "schema"

BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version     TEXT PRIMARY KEY,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  checksum    CHAR(64) NOT NULL
);
"""


@dataclass(frozen=True)
class Migration:
    version: str  # the filename, which is the identity
    path: Path
    checksum: str


@dataclass(frozen=True)
class Plan:
    apply: tuple[Migration, ...]
    skip: tuple[Migration, ...]
    conflicts: tuple[tuple[Migration, str], ...]  # (migration, recorded checksum)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def discover(schema_dir: Path, include_seeds: bool) -> list[Migration]:
    """Numbered modules in order, then numbered seeds. The glob IS the
    manifest — there is no list to forget a module from."""
    if not schema_dir.is_dir():
        raise FileNotFoundError(f"schema directory not found: {schema_dir}")
    # 000_all.sql is the interactive psql wrapper (\ir includes); the runner
    # applies the real modules directly and must not double-apply through it.
    files = [f for f in sorted(schema_dir.glob("[0-9][0-9][0-9]_*.sql")) if f.name != "000_all.sql"]
    if include_seeds:
        files += sorted((schema_dir / "seed").glob("[0-9]*_*.sql"))
    return [Migration(f.name, f, sha256_text(f.read_text(encoding="utf-8"))) for f in files]


def build_plan(migrations: list[Migration], applied: dict[str, str]) -> Plan:
    """Pure: what to apply, what to skip, and what has drifted."""
    apply: list[Migration] = []
    skip: list[Migration] = []
    conflicts: list[tuple[Migration, str]] = []
    for migration in migrations:
        recorded = applied.get(migration.version)
        if recorded is None:
            apply.append(migration)
        elif recorded == migration.checksum:
            skip.append(migration)
        else:
            conflicts.append((migration, recorded))
    return Plan(tuple(apply), tuple(skip), tuple(conflicts))


def record_sql(migration: Migration) -> str:
    """Versions are filenames and checksums are hex; both are shell- and
    SQL-safe by construction, and the pattern is enforced before use."""
    for text, label in ((migration.version, "version"), (migration.checksum, "checksum")):
        if not all(c.isalnum() or c in "._-" for c in text):
            raise ValueError(f"unsafe {label}: {text!r}")
    # psql over stdin has no parameter binding; both values are gated to
    # [A-Za-z0-9._-] by the loop above, so the interpolation cannot escape.
    return (
        "INSERT INTO schema_migrations (version, checksum) "  # noqa: S608
        f"VALUES ('{migration.version}', '{migration.checksum}');"
    )


def run_psql(psql_cmd: list[str], sql: str, *, capture: bool = False) -> str:
    """Feed SQL over stdin with ON_ERROR_STOP inside one transaction."""
    completed = subprocess.run(
        [*psql_cmd, "-v", "ON_ERROR_STOP=1", "--single-transaction", "-q", "-f", "-"],
        input=sql,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"psql exited {completed.returncode}")
    return completed.stdout if capture else ""


def query_applied(psql_cmd: list[str]) -> dict[str, str]:
    out = subprocess.run(
        [
            *psql_cmd,
            "-v",
            "ON_ERROR_STOP=1",
            "-tA",
            "-c",
            "SELECT version || '|' || checksum FROM schema_migrations",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"psql exited {out.returncode}")
    applied: dict[str, str] = {}
    for line in out.stdout.splitlines():
        if "|" in line:
            version, checksum = line.split("|", 1)
            applied[version.strip()] = checksum.strip()
    return applied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema-dir", type=Path, default=DEFAULT_SCHEMA_DIR)
    parser.add_argument("--psql", required=True, help="the psql command, e.g. 'psql -h h -d db'")
    parser.add_argument("--include-seeds", action="store_true")
    parser.add_argument("--plan", action="store_true", help="print the plan and change nothing")
    args = parser.parse_args(argv)

    psql_cmd = shlex.split(args.psql)
    migrations = discover(args.schema_dir, args.include_seeds)

    run_psql(psql_cmd, BOOTSTRAP_SQL)
    plan = build_plan(migrations, query_applied(psql_cmd))

    if plan.conflicts:
        print(
            "migration conflict: the following files changed AFTER being applied:", file=sys.stderr
        )
        for migration, recorded in plan.conflicts:
            drifted = migration.checksum[:12]
            print(
                f"  {migration.version}: recorded {recorded[:12]}, file is {drifted}",
                file=sys.stderr,
            )
        print("write a new numbered module instead of editing an applied one.", file=sys.stderr)
        return 1

    if args.plan:
        for migration in plan.skip:
            print(f"  skip   {migration.version}")
        for migration in plan.apply:
            print(f"  apply  {migration.version}")
        return 0

    for migration in plan.apply:
        sql = migration.path.read_text(encoding="utf-8") + "\n" + record_sql(migration)
        run_psql(psql_cmd, sql)
        print(f"  applied {migration.version}")
    if not plan.apply:
        print(f"  up to date ({len(plan.skip)} applied)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
