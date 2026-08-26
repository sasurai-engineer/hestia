"""Tests for the configuration contract audit.

The audit is a build gate, so the thing that matters is not that it runs but
that it *bites*: every case below plants a violation and requires a finding, or
plants a look-alike and requires silence.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config_audit


def audit(tmp: Path) -> list[config_audit.Finding]:
    """Run every check the way main() does, against a directory."""
    candidates, _ = config_audit.tracked_files(tmp)
    files = [p for p in candidates if p.is_file() and config_audit.scannable(p, tmp)]
    documented, findings = config_audit.parse_env_example(tmp / ".env.example")
    findings += config_audit.check_tracked_env_files(files, tmp)
    findings += config_audit.check_secrets(files, tmp)
    findings += config_audit.check_env_drift(files, tmp, documented)
    return findings


def rules(found: list[config_audit.Finding]) -> set[str]:
    return {f.rule for f in found}


class SecretDetectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(__import__("tempfile").mkdtemp())

    def write(self, name: str, body: str) -> None:
        path = self.tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def test_detects_high_confidence_key_shapes(self) -> None:
        self.write("a.ts", "const k = 'AKIAIOSFODNN7EXAMPLE';\n")
        self.assertIn("secret", rules(audit(self.tmp)))

    def test_a_placeholder_word_in_the_name_cannot_excuse_the_value(self) -> None:
        # The allowlist is applied to the value only. Applied to the whole match
        # it included the variable name, so `example_api_key = "<real>"` used to
        # suppress itself -- the exact defeat the tool refuses to allow.
        self.write("a.ts", 'const api_key = "aRealSecretValueHere";\n')
        self.assertIn("secret", rules(audit(self.tmp)))

    def test_allows_a_declared_placeholder_value(self) -> None:
        self.write("a.env.example", "API_KEY=change-me-please\n")
        self.assertNotIn("secret", rules(audit(self.tmp)))

    def test_detects_an_unquoted_assignment(self) -> None:
        # The commonest shape of a committed credential: a shell, YAML or CI
        # file with no quotes at all.
        self.write("deploy.sh", "export DEPLOY_TOKEN=abcdef1234567890\n")
        self.assertIn("secret", rules(audit(self.tmp)))
        self.write("conf.yaml", "password: hunter2supersecret\n")
        self.assertIn("secret", rules(audit(self.tmp)))

    def test_never_echoes_the_matched_value(self) -> None:
        # The CI job writes findings to a log that is public for a
        # source-available repository, and GitHub cannot mask a value it was
        # never told about.
        leaked = "AKIAIOSFODNN7EXAMPLE"
        self.write("a.ts", f"const k = '{leaked}';\n")
        for finding in audit(self.tmp):
            self.assertNotIn(leaked, str(finding))
            self.assertNotIn(leaked, finding.detail)

    def test_detects_a_burned_credential_on_a_very_long_line(self) -> None:
        # A minified bundle is one enormous line; skipping it skipped the
        # literal scan too.
        padding = "x" * 9000
        self.write("bundle.js", f"var a='{padding}';var b='S0crates-ChangeMe-2026!';\n")
        self.assertIn("forbidden-credential", rules(audit(self.tmp)))

    def test_honours_an_explicit_suppression(self) -> None:
        self.write("a.ts", 'const pw = "realvalue1234"; // config-audit: allow\n')
        self.assertNotIn("secret", rules(audit(self.tmp)))

    def test_scans_a_file_whose_name_matches_a_skipped_directory(self) -> None:
        # rel.parts ends with the file's own name, so a file called `build` --
        # exactly where a deploy credential gets pasted -- was never opened.
        self.write("scripts/build", "AWS=AKIAIOSFODNN7EXAMPLE\n")
        self.assertIn("secret", rules(audit(self.tmp)))

    def test_still_skips_real_build_directories(self) -> None:
        self.write("dist/bundle.js", "const k = 'AKIAIOSFODNN7EXAMPLE';\n")
        self.assertNotIn("secret", rules(audit(self.tmp)))


class EnvironmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(__import__("tempfile").mkdtemp())

    def write(self, name: str, body: str) -> None:
        (self.tmp / name).write_text(body, encoding="utf-8")

    def test_flags_a_committed_env_file(self) -> None:
        self.write(".env", "SECRET=x\n")
        self.assertIn("tracked-env-file", rules(audit(self.tmp)))

    def test_does_not_flag_the_example(self) -> None:
        self.write(".env.example", "API_BASE_URL=\n")
        self.assertNotIn("tracked-env-file", rules(audit(self.tmp)))

    def test_flags_duplicate_keys(self) -> None:
        self.write(".env.example", "A=\nA=\n")
        self.assertIn("duplicate-env-key", rules(audit(self.tmp)))

    def test_flags_an_undocumented_variable(self) -> None:
        self.write(".env.example", "KNOWN=\n")
        self.write("a.ts", "const x = process.env.UNDOCUMENTED;\n")
        self.assertIn("undocumented-env", rules(audit(self.tmp)))

    def test_accepts_a_documented_variable_and_ambient_ones(self) -> None:
        self.write(".env.example", "KNOWN=\n")
        self.write("a.ts", "const x = process.env.KNOWN; const y = process.env.NODE_ENV;\n")
        self.assertNotIn("undocumented-env", rules(audit(self.tmp)))

    def test_reads_python_environment_access_too(self) -> None:
        self.write(".env.example", "KNOWN=\n")
        self.write("a.py", "import os\nx = os.getenv('OTHER')\n")
        self.assertIn("undocumented-env", rules(audit(self.tmp)))


class GitScopeTest(unittest.TestCase):
    """An empty index is an answer, not a failure."""

    def setUp(self) -> None:
        self.tmp = Path(__import__("tempfile").mkdtemp())
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=True)

    def test_a_gitignored_env_is_not_reported_as_committed(self) -> None:
        # Falling back to a working-tree walk turned the documented setup step
        # ("Copy to .env") into a build failure.
        (self.tmp / ".gitignore").write_text(".env\n", encoding="utf-8")
        (self.tmp / ".env").write_text("SECRET=x\n", encoding="utf-8")
        _, from_index = config_audit.tracked_files(self.tmp)
        self.assertTrue(from_index)
        self.assertNotIn("tracked-env-file", rules(audit(self.tmp)))

    def test_reports_when_it_audited_nothing(self) -> None:
        # A gate that scans nothing must not report "clean".
        self.assertEqual(config_audit.main(["--root", str(self.tmp)]), 1)


class CommittedCheckoutTest(unittest.TestCase):
    """The state CI actually runs in.

    Every other test builds a scratch directory, where `git ls-files` is empty
    and the audit reports "nothing was audited". That made the whole suite pass
    vacuously while the real gate was red: the scanner's own credential
    fixtures were scanned, producing eleven findings on the first commit.
    """

    def test_the_gate_is_green_on_a_real_commit(self) -> None:
        import shutil
        import tempfile

        repo = Path(__file__).resolve().parents[2]
        staging = Path(tempfile.mkdtemp()) / "checkout"
        shutil.copytree(
            repo,
            staging,
            ignore=shutil.ignore_patterns(
                "node_modules", ".git", "dist", "coverage", ".turbo", "reports", ".env"
            ),
        )
        subprocess.run(["git", "init", "-q"], cwd=staging, check=True)
        subprocess.run(["git", "add", "-A"], cwd=staging, check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "b"],
            cwd=staging,
            check=True,
            capture_output=True,
        )

        tracked, from_index = config_audit.tracked_files(staging)
        self.assertTrue(from_index)
        self.assertGreater(len(tracked), 20, "the copy did not commit anything")

        result = subprocess.run(
            [sys.executable, str(staging / "scripts" / "config_audit.py")],
            cwd=staging,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"the audit fails its own repository:\n{result.stdout}{result.stderr}",
        )

    def test_the_exemption_survives_a_different_root(self) -> None:
        # The exclusion used to be a repo-root-relative string literal, so it
        # stopped matching the moment --root pointed anywhere else and the tool
        # flagged its own pattern table.
        repo = Path(__file__).resolve().parents[2]
        self.assertEqual(
            [f for f in audit(repo / "scripts") if f.rule in {"secret", "forbidden-credential"}],
            [],
        )


class SelfTest(unittest.TestCase):
    def test_the_audit_does_not_flag_its_own_pattern_table(self) -> None:
        root = Path(__file__).resolve().parents[2]
        found = [f for f in audit(root / "scripts") if f.rule in {"secret", "forbidden-credential"}]
        self.assertEqual(found, [], f"self-scan produced findings: {found}")


if __name__ == "__main__":
    unittest.main()
