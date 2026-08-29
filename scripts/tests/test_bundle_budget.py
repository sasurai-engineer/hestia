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
        # --min-routes 1: this case exercises the budget, not the floor.
        code, out = self.run_main(["--app", str(app), "--budget-kb", "180", "--min-routes", "1"])
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
        code, out = self.run_main(["--app", str(app), "--budget-kb", "1", "--min-routes", "1"])
        self.assertEqual(code, 1)
        self.assertIn("/reports/page", out)
        self.assertIn("over the 1 KB", out)

    def test_missing_build_fails_loudly(self) -> None:
        empty = Path(tempfile.mkdtemp())
        code, out = self.run_main(["--app", str(empty)])
        self.assertEqual(code, 1)
        self.assertIn("no build manifest", out)

    def test_a_manifest_that_measures_nothing_is_a_failure(self) -> None:
        # The hole this gate had: only routes OVER budget failed it, so an
        # empty or shape-shifted manifest passed having measured nothing.
        app = make_build({})
        code, out = self.run_main(["--app", str(app)])
        self.assertEqual(code, 1)
        self.assertIn("measured 0 route(s)", out)

    def test_a_thin_manifest_trips_the_floor(self) -> None:
        app = make_build({"/page": [("static/chunks/a.js", b"1;")]})
        code, out = self.run_main(["--app", str(app), "--min-routes", "5"])
        self.assertEqual(code, 1)
        self.assertIn("refusing to pass", out)


class LayoutTest(unittest.TestCase):
    """A route is measured with the layouts that wrap it, or it is not measured."""

    def test_route_size_includes_the_root_layout_chunk(self) -> None:
        page = b"const page = 1;" * 50
        layout = b"const palette = 2;" * 200
        app = make_build(
            {
                "/layout": [("static/chunks/app/layout.js", layout)],
                "/page": [("static/chunks/app/page.js", page)],
            }
        )
        sizes = check_bundle_budget.route_sizes(app / ".next")
        expected = len(gzip.compress(page, compresslevel=6)) + len(
            gzip.compress(layout, compresslevel=6)
        )
        self.assertEqual(sizes["/page"], expected)

    def test_a_layout_is_not_reported_as_a_route(self) -> None:
        app = make_build(
            {
                "/layout": [("static/chunks/app/layout.js", b"x;")],
                "/page": [("static/chunks/app/page.js", b"y;")],
            }
        )
        self.assertEqual(list(check_bundle_budget.route_sizes(app / ".next")), ["/page"])

    def test_a_nested_layout_wraps_only_its_own_subtree(self) -> None:
        # Pure key arithmetic: no build needed, only the manifest's key set.
        make_build(
            {
                "/layout": [("static/chunks/root.js", b"r;")],
                "/property/layout": [("static/chunks/prop.js", b"p;")],
                "/property/[id]/page": [("static/chunks/dossier.js", b"d;")],
                "/vendors/page": [("static/chunks/vendors.js", b"v;")],
            }
        )
        keys = {"/layout", "/property/layout", "/property/[id]/page", "/vendors/page"}
        self.assertEqual(
            check_bundle_budget.wrapping_layouts("/property/[id]/page", keys),
            ["/layout", "/property/layout"],
        )
        self.assertEqual(check_bundle_budget.wrapping_layouts("/vendors/page", keys), ["/layout"])

    def test_a_chunk_shared_by_route_and_layout_is_counted_once(self) -> None:
        shared = b"const framework = 1;" * 40
        app = make_build(
            {
                "/layout": [("static/chunks/shared.js", shared)],
                "/page": [("static/chunks/shared.js", shared)],
            }
        )
        sizes = check_bundle_budget.route_sizes(app / ".next")
        self.assertEqual(sizes["/page"], len(gzip.compress(shared, compresslevel=6)))


if __name__ == "__main__":
    unittest.main()
