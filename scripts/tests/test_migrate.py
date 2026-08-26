"""Tests for the migration runner's pure core.

The psql-execution half is exercised end to end by verify-schema.sh in CI —
including the idempotent second run — so these tests own what a database
cannot show: discovery order, checksum identity, drift detection, and the
safety of what gets interpolated.
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import migrate


def make_tree(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp())
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


class DiscoveryTest(unittest.TestCase):
    def test_orders_modules_then_seeds_and_skips_the_psql_wrapper(self) -> None:
        root = make_tree(
            {
                "002_b.sql": "b",
                "001_a.sql": "a",
                "000_all.sql": "\\ir 001_a.sql",
                "notes.md": "not sql",
                "seed/901_y.sql": "y",
                "seed/900_x.sql": "x",
            }
        )
        names = [m.version for m in migrate.discover(root, include_seeds=True)]
        self.assertEqual(names, ["001_a.sql", "002_b.sql", "900_x.sql", "901_y.sql"])

    def test_seeds_are_opt_in(self) -> None:
        root = make_tree({"001_a.sql": "a", "seed/900_x.sql": "x"})
        names = [m.version for m in migrate.discover(root, include_seeds=False)]
        self.assertEqual(names, ["001_a.sql"])

    def test_a_missing_directory_is_loud(self) -> None:
        with self.assertRaises(FileNotFoundError):
            migrate.discover(Path(tempfile.mkdtemp()) / "absent", include_seeds=False)

    def test_checksums_are_content_identity(self) -> None:
        root = make_tree({"001_a.sql": "CREATE TABLE t ();"})
        first = migrate.discover(root, False)[0].checksum
        (root / "001_a.sql").write_text("CREATE TABLE t (x int);", encoding="utf-8")
        second = migrate.discover(root, False)[0].checksum
        self.assertNotEqual(first, second)
        self.assertEqual(len(first), 64)


class PlanTest(unittest.TestCase):
    def migrations(self) -> list[migrate.Migration]:
        root = make_tree({"001_a.sql": "a", "002_b.sql": "b"})
        return migrate.discover(root, False)

    def test_fresh_database_applies_everything(self) -> None:
        plan = migrate.build_plan(self.migrations(), applied={})
        self.assertEqual([m.version for m in plan.apply], ["001_a.sql", "002_b.sql"])
        self.assertEqual(plan.skip, ())
        self.assertEqual(plan.conflicts, ())

    def test_applied_and_unchanged_is_skipped(self) -> None:
        migrations = self.migrations()
        applied = {m.version: m.checksum for m in migrations}
        plan = migrate.build_plan(migrations, applied)
        self.assertEqual(plan.apply, ())
        self.assertEqual(len(plan.skip), 2)

    def test_edited_after_apply_is_a_conflict_not_a_reapply(self) -> None:
        migrations = self.migrations()
        applied = {migrations[0].version: "0" * 64}
        plan = migrate.build_plan(migrations, applied)
        self.assertEqual([m.version for m, _ in plan.conflicts], ["001_a.sql"])
        # The PLAN still lists the conflict-free module; main() refuses to
        # run while any conflict exists, so nothing is actually applied
        # until the drift is resolved.
        self.assertEqual([m.version for m in plan.apply], ["002_b.sql"])


class RecordSqlTest(unittest.TestCase):
    def test_interpolation_is_pattern_gated(self) -> None:
        good = migrate.Migration("001_a.sql", Path("x"), "ab" * 32)
        self.assertIn("'001_a.sql'", migrate.record_sql(good))
        evil = migrate.Migration("001'; DROP TABLE ledger_events; --", Path("x"), "ab" * 32)
        with self.assertRaises(ValueError):
            migrate.record_sql(evil)


class RealSchemaTest(unittest.TestCase):
    def test_the_actual_schema_directory_discovers_cleanly(self) -> None:
        migrations = migrate.discover(migrate.DEFAULT_SCHEMA_DIR, include_seeds=True)
        names = [m.version for m in migrations]
        self.assertIn("001_foundations.sql", names)
        self.assertIn("007_deadlines_hazards_market.sql", names)
        self.assertNotIn("000_all.sql", names)
        # The shared federal seed exists, and at least one state pack matches
        # the pack convention -- no specific state is load-bearing here.
        self.assertIn("899_federal.sql", names)
        packs = [n for n in names if re.fullmatch(r"9\d\d_jurisdictions_[a-z_]+\.sql", n)]
        self.assertTrue(packs, "no state pack discovered")
        # Modules strictly before every seed, and the federal seed strictly
        # before every state pack (packs may assume 899, nothing else).
        first_seed = names.index("899_federal.sql")
        self.assertTrue(all(n < "899" for n in names[:first_seed]))
        self.assertTrue(all(first_seed < names.index(p) for p in packs))


if __name__ == "__main__":
    unittest.main()
