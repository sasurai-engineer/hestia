"""Tests for the first-load JavaScript budget gate.

The real manifest is exercised in CI against an actual ``next build``; these
tests own the arithmetic — that sizes are gzip wire sizes, that non-JS
assets stay out of the sum, that a route over budget fails with its figure
printed, and that a missing build fails loudly instead of passing quietly.
"""

from __future__ import annotations

import gzip
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_bundle_budget


def make_build(routes: dict[str, list[tuple[str, bytes]]]) -> Path:
    """Fabricate an app dir holding .next with a manifest and real chunks."""
    app = Path(tempfile.mkdtemp())
    next_dir = app / ".next"
    pages: dict[str, list[str]] = {}
    for route, assets in routes.items():
        pages[route] = []
        for name, body in assets:
            path = next_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            pages[route].append(name)
    next_dir.mkdir(parents=True, exist_ok=True)
    (next_dir / "app-build-manifest.json").write_text(json.dumps({"pages": pages}))
    return app


class RouteSizesTest(unittest.TestCase):
    def test_sums_gzip_sizes_and_ignores_non_js(self) -> None:
        chunk = b"const portfolio = 1;" * 100
        app = make_build(
            {
                "/page": [
                    ("static/chunks/main.js", chunk),
                    ("static/css/app.css", b"body { color: red }" * 100),
                ]
            }
        )
        sizes = check_bundle_budget.route_sizes(app / ".next")
        self.assertEqual(sizes, {"/page": len(gzip.compress(chunk, compresslevel=6))})

    def test_shared_chunks_count_toward_every_route(self) -> None:
        shared = b"function framework() {}" * 200
        app = make_build(
            {
                "/page": [("static/chunks/fw.js", shared)],
                "/vendors/page": [("static/chunks/fw.js", shared)],
            }
        )
        sizes = check_bundle_budget.route_sizes(app / ".next")
        self.assertEqual(sizes["/page"], sizes["/vendors/page"])
        self.assertGreater(sizes["/page"], 0)


class GateTest(unittest.TestCase):
    def run_main(self, argv: list[str]) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = check_bundle_budget.main(argv)
        return code, out.getvalue()

    def test_under_budget_passes(self) -> None:
        app = make_build({"/page": [("static/chunks/tiny.js", b"1;")]})
        code, out = self.run_main(["--app", str(app), "--budget-kb", "180"])
        self.assertEqual(code, 0)
        self.assertIn("every route under", out)

    def test_over_budget_fails_and_names_the_route(self) -> None:
        # Deterministic high-entropy bytes (chained digests) so the gzip
        # wire size genuinely exceeds 1 KB — no randomness in a test.
        import hashlib

        block = b"hestia"
        chunks: list[bytes] = []
        for _ in range(128):
            block = hashlib.sha256(block).digest()
            chunks.append(block)
        heavy = b"".join(chunks)
        app = make_build({"/reports/page": [("static/chunks/heavy.js", heavy)]})
        code, out = self.run_main(["--app", str(app), "--budget-kb", "1"])
        self.assertEqual(code, 1)
        self.assertIn("/reports/page", out)
        self.assertIn("over the 1 KB", out)

    def test_missing_build_fails_loudly(self) -> None:
        empty = Path(tempfile.mkdtemp())
        code, out = self.run_main(["--app", str(empty)])
        self.assertEqual(code, 1)
        self.assertIn("no build manifest", out)


if __name__ == "__main__":
    unittest.main()
