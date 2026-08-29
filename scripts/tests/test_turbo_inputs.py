"""Tests for the turbo-inputs law.

The real repository is checked by the script itself in CI; these own the
arithmetic of the check -- that a hole is found, that a covered directory is
not reported, and that the two shapes turbo allows (no declared inputs, a
package-specific task override) are read correctly.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_turbo_inputs


def make_repo(
    turbo: dict,
    pkg: str = "apps/web",
    include: str | None = None,
    dirs: tuple[str, ...] = ("src", "tests"),
) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "turbo.json").write_text(json.dumps(turbo))
    p = root / pkg
    p.mkdir(parents=True)
    (p / "package.json").write_text('{"name": "web"}')
    for d in dirs:
        (p / d).mkdir()
    if include is not None:
        (p / "vitest.config.ts").write_text(
            f"export default {{ test: {{ include: [{include}] }} }}"
        )
    return root


TASKS_NARROW = {"tasks": {"test": {"inputs": ["src/**", "vitest.config.*"]}}}
TASKS_WIDE = {"tasks": {"test": {"inputs": ["src/**", "tests/**", "fixtures/**"]}}}


class LawTest(unittest.TestCase):
    def test_names_a_directory_the_task_reads_but_does_not_hash(self) -> None:
        root = make_repo(TASKS_NARROW, include="'tests/**/*.test.ts'")
        code = check_turbo_inputs.main(["--root", str(root)])
        self.assertEqual(code, 1)

    def test_passes_when_the_inputs_cover_the_globs(self) -> None:
        root = make_repo(TASKS_WIDE, include="'tests/**/*.test.ts'")
        self.assertEqual(check_turbo_inputs.main(["--root", str(root)]), 0)

    def test_a_directory_the_globs_never_touch_is_not_demanded(self) -> None:
        # src-only suite under narrow inputs: nothing missing, even though
        # a tests/ directory happens to exist on disk.
        root = make_repo(TASKS_NARROW, include="'src/**/*.test.ts'")
        self.assertEqual(check_turbo_inputs.main(["--root", str(root)]), 0)

    def test_fixtures_are_demanded_whenever_the_directory_exists(self) -> None:
        # The engines read fixtures/engine-fixtures.json without any glob
        # naming it, which is exactly how that hole stayed open.
        root = make_repo(TASKS_NARROW, include="'src/**/*.test.ts'", dirs=("src", "fixtures"))
        self.assertEqual(check_turbo_inputs.main(["--root", str(root)]), 1)

    def test_a_package_specific_task_override_is_read_instead_of_the_default(self) -> None:
        turbo = {
            "tasks": {
                "test": {"inputs": ["src/**"]},
                "web#test": {"inputs": ["src/**", "tests/**"]},
            }
        }
        root = make_repo(turbo, include="'tests/**/*.test.ts'")
        self.assertEqual(check_turbo_inputs.main(["--root", str(root)]), 0)

    def test_a_task_with_no_declared_inputs_is_safe_by_default(self) -> None:
        # Turbo hashes the whole package when inputs are omitted, so there is
        # nothing to refuse -- the law must not manufacture a finding.
        root = make_repo({"tasks": {"test": {}}}, include="'tests/**/*.test.ts'")
        self.assertEqual(check_turbo_inputs.main(["--root", str(root)]), 0)

    def test_a_package_without_vitest_is_ignored(self) -> None:
        root = make_repo(TASKS_NARROW, include=None)
        self.assertEqual(check_turbo_inputs.main(["--root", str(root)]), 0)


if __name__ == "__main__":
    unittest.main()
