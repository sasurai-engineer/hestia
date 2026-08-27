"""The extraction loop, end to end: upload -> extract -> review -> apply.

The fixture is a real two-page PDF (tests/fixtures/monmouth-closing.pdf,
regenerable by make_monmouth_closing.py beside it). Applied documents are
ledger-pinned and survive `clean`, so every test uploads UNIQUE bytes — a
trailing PDF comment changes the hash without changing what parses.
"""

from __future__ import annotations

import datetime as dt
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from hestia_api import documents, extraction_parse
from starlette.datastructures import UploadFile

FIXTURE = (Path(__file__).parent / "fixtures" / "monmouth-closing.pdf").read_bytes()
KY_STATE = "a0000000-0000-4000-8000-000000000010"

REQUIRED_PATHS = (
    "settlement.closing_date",
    "settlement.sale_price",
    "settlement.capitalizable_closing_costs",
    "settlement.property_address",
)


def pdf_variant(tag: str) -> bytes:
    """The same statement under a fresh content hash: a comment after %%EOF
    is outside every object a reader touches."""
    return FIXTURE + b"\n% " + tag.encode()


def upload(
    client: TestClient,
    property_id: str,
    content: bytes,
    *,
    kind: str = "settlement_statement",
    filename: str = "closing.pdf",
) -> dict[str, Any]:
    response = client.post(
        "/documents",
        data={"kind": kind, "property_id": property_id},
        files={"file": (filename, content, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def review(
    client: TestClient, doc_id: str, field_path: str, action: str, value: str | None = None
) -> dict[str, Any]:
    response = client.post(
        f"/documents/{doc_id}/review",
        json={"field_path": field_path, "action": action, "value": value},
    )
    assert response.status_code == 200, response.text
    return response.json()


def ratify(client: TestClient, doc_id: str) -> dict[str, Any]:
    detail = None
    for path in REQUIRED_PATHS:
        detail = review(client, doc_id, path, "accept")
    assert detail is not None and detail["status"] == "confirmed"
    return detail


class TestUploadAndExtract:
    def test_the_monmouth_statement_extracts_every_field(
        self, newport_property: str, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        detail = upload(client, newport_property, pdf_variant("full-extract"))
        assert detail["status"] == "extracted"
        assert detail["property_labels"] == ["998 Monmouth"]
        assert detail["open_review_count"] == 0
        by_path = {f["field_path"]: f for f in detail["fields"]}
        assert len(by_path) == 8
        assert by_path["settlement.closing_date"]["normalised_value"] == "2019-04-11"
        assert by_path["settlement.sale_price"]["normalised_value"] == "187500.00"
        costs = by_path["settlement.capitalizable_closing_costs"]
        # The printed total foots against the itemized charges, so the parser
        # is CERTAIN; page 2 is where the itemization lives.
        assert costs["normalised_value"] == "1783.00"
        assert Decimal(costs["confidence"]) == 1
        assert costs["page"] == 2
        assert by_path["settlement.sale_price"]["page"] == 1
        assert all(f["model_id"] == extraction_parse.MODEL_ID for f in by_path.values())
        # Machine done, human not yet: values are effective but not ratified.
        assert by_path["settlement.sale_price"]["effective_value"] == "187500.00"
        # The engines' preview: basis math happens server-side.
        assert Decimal(detail["suggestion"]["total_basis"]) == Decimal("189283.00")
        assert detail["suggestion"]["address_matches"] is True
        assert detail["suggestion"]["suggested_land_value"] is None
        run = conn.execute(
            "SELECT status::text AS status, raw_response FROM ingestion_runs"
            " WHERE provider = 'extractor:settlement_statement'"
            " ORDER BY requested_at DESC LIMIT 1"
        ).fetchone()
        assert run is not None and run["status"] == "ok"
        assert any(f["field_path"] == "settlement.sale_price" for f in run["raw_response"])

    def test_reupload_of_identical_bytes_is_a_409(
        self, newport_property: str, client: TestClient
    ) -> None:
        content = pdf_variant("dedupe")
        upload(client, newport_property, content)
        response = client.post(
            "/documents",
            data={"kind": "settlement_statement", "property_id": newport_property},
            files={"file": ("again.pdf", content, "application/pdf")},
        )
        assert response.status_code == 409

    def test_a_kind_without_a_parser_waits_pending(
        self, newport_property: str, client: TestClient
    ) -> None:
        detail = upload(
            client, newport_property, b"jpeg bytes pretend", kind="photo", filename="roof.jpg"
        )
        assert detail["status"] == "pending"
        assert detail["fields"] == []
        assert detail["suggestion"] is None
        assert detail["has_content"] is True

    def test_a_text_statement_with_gaps_flags_skeletons(
        self, newport_property: str, client: TestClient
    ) -> None:
        text = "﻿Settlement Date: 04/11/2019\nSeller: V. Endor\n".encode()
        detail = upload(client, newport_property, text, filename="partial.txt")
        assert detail["status"] == "needs_review"
        by_path = {f["field_path"]: f for f in detail["fields"]}
        assert by_path["settlement.closing_date"]["normalised_value"] == "2019-04-11"
        sale = by_path["settlement.sale_price"]
        assert sale["raw_value"] is None and sale["needs_review"] is True
        assert sale["effective_value"] is None
        # An optional field the parser never met has no row at all.
        assert by_path["settlement.buyer_name"]["model_id"] is None
        assert by_path["settlement.buyer_name"]["needs_review"] is False
        # No basis values yet, no preview.
        assert detail["suggestion"] is None

    def test_unreadable_uploads_are_422(self, newport_property: str, client: TestClient) -> None:
        for content in (b"%PDF-1.4 but nothing else", b"\xff\xfe not text"):
            response = client.post(
                "/documents",
                data={"kind": "settlement_statement", "property_id": newport_property},
                files={"file": ("bad.pdf", content, "application/pdf")},
            )
            assert response.status_code == 422

    def test_upload_guards(
        self,
        newport_property: str,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        response = client.post(
            "/documents",
            data={"kind": "settlement_statement", "property_id": str(dt.date.today())},
            files={"file": ("x.pdf", b"%PDF", "application/pdf")},
        )
        assert response.status_code == 422  # not even a uuid
        response = client.post(
            "/documents",
            data={
                "kind": "settlement_statement",
                "property_id": "00000000-0000-4000-8000-000000000000",
            },
            files={"file": ("x.pdf", pdf_variant("no-prop"), "application/pdf")},
        )
        assert response.status_code == 404
        monkeypatch.setattr(documents, "MAX_BYTES", 64)
        response = client.post(
            "/documents",
            data={"kind": "settlement_statement", "property_id": newport_property},
            files={"file": ("big.pdf", pdf_variant("too-big"), "application/pdf")},
        )
        assert response.status_code == 413

    def test_the_inbox_filters_by_status(self, newport_property: str, client: TestClient) -> None:
        detail = upload(client, newport_property, pdf_variant("inbox"))
        rows = client.get("/documents", params={"status": "extracted"}).json()
        assert any(row["id"] == detail["id"] for row in rows)
        assert all(row["status"] == "extracted" for row in rows)
        everything = client.get("/documents").json()
        assert any(row["id"] == detail["id"] for row in everything)

    def test_content_round_trips(self, newport_property: str, client: TestClient) -> None:
        content = pdf_variant("round-trip")
        detail = upload(client, newport_property, content)
        response = client.get(f"/documents/{detail['id']}/content")
        assert response.status_code == 200
        assert response.content == content
        assert "closing.pdf" in response.headers["content-disposition"]

    def test_a_hostile_upload_cannot_run_on_the_api_origin(
        self, newport_property: str, client: TestClient
    ) -> None:
        """The uploader chooses the mime type; it must never become script on
        our own origin."""
        response = client.post(
            "/documents",
            data={"kind": "other", "property_id": newport_property},
            files={
                "file": (
                    "evil.html",
                    b"<script>alert(document.domain)</script>",
                    "text/html",
                )
            },
        )
        assert response.status_code == 201
        content = client.get(f"/documents/{response.json()['id']}/content")
        assert content.status_code == 200
        assert content.content == b"<script>alert(document.domain)</script>"
        # Downloaded as untyped bytes, never rendered as HTML.
        assert content.headers["content-type"] == "application/octet-stream"
        assert content.headers["x-content-type-options"] == "nosniff"
        assert content.headers["content-disposition"].startswith("attachment;")

    def test_a_pdf_still_opens_inline_under_its_own_name(
        self, newport_property: str, client: TestClient
    ) -> None:
        detail = upload(client, newport_property, pdf_variant("inline-view"))
        content = client.get(f"/documents/{detail['id']}/content")
        assert content.headers["content-type"] == "application/pdf"
        assert content.headers["content-disposition"].startswith('inline; filename="closing.pdf"')

    def test_a_non_ascii_filename_rides_in_filename_star(
        self, newport_property: str, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        detail = upload(client, newport_property, pdf_variant("kanji-name"))
        conn.execute(
            "UPDATE source_documents SET filename = %s WHERE id = %s",
            ("譲渡証書.pdf", detail["id"]),
        )
        conn.commit()
        disposition = client.get(f"/documents/{detail['id']}/content").headers[
            "content-disposition"
        ]
        # ASCII-only fallback for old clients, the real name percent-encoded.
        assert 'filename=".pdf"' in disposition
        assert "filename*=UTF-8''%E8%AD%B2%E6%B8%A1%E8%A8%BC%E6%9B%B8.pdf" in disposition

    def test_missing_documents_are_404(self, clean: None, client: TestClient) -> None:
        ghost = "00000000-0000-4000-8000-00000000dead"
        assert client.get(f"/documents/{ghost}").status_code == 404
        assert client.get(f"/documents/{ghost}/content").status_code == 404
        assert client.post(f"/documents/{ghost}/extract").status_code == 404
        assert (
            client.post(
                f"/documents/{ghost}/review",
                json={"field_path": "settlement.sale_price", "action": "accept"},
            ).status_code
            == 404
        )
        assert (
            client.post(f"/documents/{ghost}/apply", json={"land_value": "1.00"}).status_code == 404
        )


class TestReview:
    def test_accept_correct_reject_round_trip(
        self, newport_property: str, client: TestClient
    ) -> None:
        detail = upload(client, newport_property, pdf_variant("review-loop"))
        doc_id = detail["id"]
        after = review(client, doc_id, "settlement.sale_price", "accept")
        sale = next(f for f in after["fields"] if f["field_path"] == "settlement.sale_price")
        assert sale["accepted_value"] == "187500.00"
        assert sale["reviewed_by"] == "system"
        after = review(
            client, doc_id, "settlement.capitalizable_closing_costs", "correct", "$1,900.00"
        )
        costs = next(
            f
            for f in after["fields"]
            if f["field_path"] == "settlement.capitalizable_closing_costs"
        )
        assert costs["accepted_value"] == "1900.00"
        assert costs["effective_value"] == "1900.00"
        # The corrected figure flows into the server-computed preview.
        assert Decimal(after["suggestion"]["total_basis"]) == Decimal("189400.00")
        after = review(client, doc_id, "settlement.loan_amount", "reject")
        loan = next(f for f in after["fields"] if f["field_path"] == "settlement.loan_amount")
        assert loan["accepted_value"] is None
        assert loan["reviewed_at"] is not None
        assert loan["effective_value"] is None

    def test_confirmed_requires_every_required_field_ratified(
        self, newport_property: str, client: TestClient
    ) -> None:
        detail = upload(client, newport_property, pdf_variant("ratify-gate"))
        doc_id = detail["id"]
        for path in REQUIRED_PATHS[:-1]:
            detail = review(client, doc_id, path, "accept")
            assert detail["status"] == "extracted"
        detail = review(client, doc_id, REQUIRED_PATHS[-1], "accept")
        assert detail["status"] == "confirmed"
        # Rejecting a required field reopens the gate.
        detail = review(client, doc_id, "settlement.sale_price", "reject")
        assert detail["status"] == "extracted"

    def test_correcting_a_skeleton_and_supplying_an_optional(
        self, newport_property: str, client: TestClient
    ) -> None:
        text = b"Settlement Date: 04/11/2019\n"
        detail = upload(client, newport_property, text, filename="skeleton.txt")
        doc_id = detail["id"]
        detail = review(client, doc_id, "settlement.sale_price", "correct", "200000")
        sale = next(f for f in detail["fields"] if f["field_path"] == "settlement.sale_price")
        assert sale["accepted_value"] == "200000.00"
        assert sale["needs_review"] is False
        # buyer_name never got a row; the human supplies it whole.
        detail = review(client, doc_id, "settlement.buyer_name", "correct", "Delta Holdings LLC")
        buyer = next(f for f in detail["fields"] if f["field_path"] == "settlement.buyer_name")
        assert buyer["accepted_value"] == "Delta Holdings LLC"
        assert buyer["raw_value"] is None

    def test_review_validation(self, newport_property: str, client: TestClient) -> None:
        text = b"Settlement Date: 04/11/2019\n"
        detail = upload(client, newport_property, text, filename="validation.txt")
        doc_id = detail["id"]

        def attempt(path: str, action: str, value: str | None = None) -> int:
            return client.post(
                f"/documents/{doc_id}/review",
                json={"field_path": path, "action": action, "value": value},
            ).status_code

        assert attempt("settlement.sale_price", "accept") == 422  # skeleton, nothing there
        assert attempt("settlement.buyer_name", "accept") == 422  # no row at all
        assert attempt("settlement.escrow_agent", "accept") == 422  # no such spec
        assert attempt("settlement.sale_price", "correct") == 422  # no value given
        assert attempt("settlement.sale_price", "correct", "a lot") == 422
        assert attempt("settlement.closing_date", "correct", "sometime") == 422
        assert attempt("settlement.buyer_name", "correct", "   ") == 422

    def test_a_suspect_derived_sum_routes_to_review(
        self, newport_property: str, client: TestClient
    ) -> None:
        text = (
            b"Settlement Date: 04/11/2019\n"
            b"Property: 998 Monmouth St, Newport, KY 41071\n"
            b"Sale Price of Property                    $187,500.00\n"
            b"Owner's Title Insurance Policy               $712.00\n"
            b"Survey                                       $325.00\n"
        )
        detail = upload(client, newport_property, text, filename="derived.txt")
        costs = next(
            f
            for f in detail["fields"]
            if f["field_path"] == "settlement.capitalizable_closing_costs"
        )
        # No printed total: the parser sums and shows its working, flagged.
        assert costs["normalised_value"] == "1037.00"
        assert Decimal(costs["confidence"]) == Decimal("0.9")
        assert costs["needs_review"] is True
        assert "Owner's Title Insurance Policy $712.00" in costs["raw_value"]
        assert detail["status"] == "needs_review"


class TestReExtract:
    def test_reviews_survive_a_re_extract(self, newport_property: str, client: TestClient) -> None:
        detail = upload(client, newport_property, pdf_variant("re-extract"))
        doc_id = detail["id"]
        review(client, doc_id, "settlement.sale_price", "correct", "190000")
        response = client.post(f"/documents/{doc_id}/extract")
        assert response.status_code == 200
        after = response.json()
        sale = next(f for f in after["fields"] if f["field_path"] == "settlement.sale_price")
        # The human's ratification outlives the parser re-run...
        assert sale["accepted_value"] == "190000.00"
        # ...while unreviewed fields are freshly re-extracted.
        costs = next(
            f
            for f in after["fields"]
            if f["field_path"] == "settlement.capitalizable_closing_costs"
        )
        assert costs["accepted_value"] is None
        assert costs["normalised_value"] == "1783.00"

    def test_a_blobless_document_re_extracts_to_nothing(
        self, newport_property: str, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        row = conn.execute(
            """
            INSERT INTO source_documents (kind, filename, content_hash, status)
            VALUES ('bank_statement', 'old.csv', repeat('e', 64), 'pending')
            RETURNING id::text
            """
        ).fetchone()
        assert row is not None
        conn.commit()
        response = client.post(f"/documents/{row['id']}/extract")
        assert response.status_code == 200
        assert response.json()["status"] == "pending"

    def test_a_blob_the_new_parser_cannot_read_is_a_422(
        self,
        newport_property: str,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A kind can gain a parser after upload; bytes that parser cannot
        read surface as a 422 at re-extract, not a 500."""
        detail = upload(
            client, newport_property, b"\xff\xfe binary", kind="photo", filename="cam.raw"
        )
        monkeypatch.setitem(extraction_parse.PARSERS, "photo", extraction_parse.parse_settlement)
        response = client.post(f"/documents/{detail['id']}/extract")
        assert response.status_code == 422

    def test_a_kind_without_specs_stays_pending_even_with_a_parser(
        self,
        newport_property: str,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        detail = upload(
            client,
            newport_property,
            b"Settlement Date: 04/11/2019\n",
            kind="photo",
            filename="note.txt",
        )
        monkeypatch.setitem(extraction_parse.PARSERS, "photo", extraction_parse.parse_settlement)
        response = client.post(f"/documents/{detail['id']}/extract")
        assert response.status_code == 200
        after = response.json()
        # The parser ran, but the registry defines nothing for photos: no
        # rows appear and the status honestly stands.
        assert after["status"] == "pending"
        assert after["fields"] == []


class TestReviewFindings:
    """One pin per defect the adversarial review of this increment confirmed."""

    def test_applied_is_terminal_even_under_a_concurrent_review(
        self, newport_property: str, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """A review that read the document BEFORE an apply committed must not
        write its status back — that would let one purchase apply twice into
        an append-only ledger."""
        detail = upload(client, newport_property, pdf_variant("terminal-state"))
        doc_id = detail["id"]
        ratify(client, doc_id)
        assert (
            client.post(f"/documents/{doc_id}/apply", json={"land_value": "0.00"}).status_code
            == 201
        )
        # The stale write the racing review would have issued, verbatim.
        conn.execute(
            "UPDATE source_documents SET status = 'confirmed'"
            " WHERE id = %s AND status::text <> 'applied'",
            (doc_id,),
        )
        conn.commit()
        assert client.get(f"/documents/{doc_id}").json()["status"] == "applied"
        assert (
            client.post(f"/documents/{doc_id}/apply", json={"land_value": "0.00"}).status_code
            == 409
        )

    def test_accepting_an_unparseable_value_is_refused_not_ratified(
        self, newport_property: str, client: TestClient
    ) -> None:
        """The parser flags a date it could not read; one click must not turn
        that into a ratified fact that explodes at apply."""
        text = b"Settlement Date: TBD at recording\n"
        detail = upload(client, newport_property, text, filename="tbd.txt")
        doc_id = detail["id"]
        date_field = next(
            f for f in detail["fields"] if f["field_path"] == "settlement.closing_date"
        )
        assert date_field["needs_review"] is True
        response = client.post(
            f"/documents/{doc_id}/review",
            json={"field_path": "settlement.closing_date", "action": "accept"},
        )
        assert response.status_code == 422
        assert "not a date" in response.json()["detail"]
        assert client.get(f"/documents/{doc_id}").json()["status"] == "needs_review"

    def test_non_finite_money_is_not_a_money_amount(
        self, newport_property: str, client: TestClient
    ) -> None:
        """Decimal parses NaN and Infinity happily; both would poison every
        total downstream and make the document unrenderable."""
        detail = upload(client, newport_property, pdf_variant("nan-money"))
        doc_id = detail["id"]
        for hostile in ("nan", "NaN", "Infinity", "-inf"):
            response = client.post(
                f"/documents/{doc_id}/review",
                json={
                    "field_path": "settlement.sale_price",
                    "action": "correct",
                    "value": hostile,
                },
            )
            assert response.status_code == 422, hostile
        assert client.get(f"/documents/{doc_id}").status_code == 200

    def test_the_inbox_does_not_multiply_counts_across_properties(
        self, newport_property: str, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """document_properties is many-to-many by design (module 005 names
        the multi-property statement); the inbox must not cross-join it with
        the field rows."""
        detail = upload(client, newport_property, pdf_variant("fan-out"))
        doc_id = detail["id"]
        entity = client.post("/entities", json={"name": "Fan Out", "kind": "llc"}).json()
        other = client.post(
            "/properties",
            json={
                "entity_id": entity["id"],
                "label": "Second Of Two",
                "street_1": "2 Second St",
                "city": "Newport",
                "state": "KY",
                "postal_code": "41071",
                "kind": "single_family",
            },
        ).json()
        conn.execute(
            "INSERT INTO document_properties (document_id, property_id) VALUES (%s, %s)",
            (doc_id, other["id"]),
        )
        conn.commit()
        (row,) = [r for r in client.get("/documents").json() if r["id"] == doc_id]
        assert row["extracted_count"] == 8  # the eight fields, not sixteen
        assert row["open_review_count"] == 0
        assert sorted(row["property_labels"]) == ["998 Monmouth", "Second Of Two"]

    def test_the_land_suggestion_cites_the_closing_year_assessment(
        self, newport_property: str, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """A 2019 purchase allocated by a 2026 ratio is not defensible."""
        for year, land, total in ((2019, 30000, 160000), (2026, 90000, 300000)):
            conn.execute(
                """
                INSERT INTO assessments
                  (property_id, jurisdiction_id, tax_year, assessed_land, assessed_total)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (property_id, jurisdiction_id, tax_year) DO NOTHING
                """,
                (newport_property, KY_STATE, year, land, total),
            )
        conn.commit()
        detail = upload(client, newport_property, pdf_variant("contemporaneous"))
        suggestion = ratify(client, detail["id"])["suggestion"]
        assert "assessment 2019" in suggestion["suggestion_citation"]
        assert Decimal(suggestion["suggested_land_value"]) == Decimal("35490.56")

    def test_the_address_check_does_not_match_a_different_street_number(
        self, newport_property: str, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """`998 Monmouth St` must not be found inside `1998 Monmouth St`."""
        detail = upload(client, newport_property, pdf_variant("address-check"))
        doc_id = detail["id"]
        client.post(
            f"/documents/{doc_id}/review",
            json={
                "field_path": "settlement.property_address",
                "action": "correct",
                "value": "1998 Monmouth Street, Newport, KY 41071",
            },
        )
        for path in (
            "settlement.closing_date",
            "settlement.sale_price",
            "settlement.capitalizable_closing_costs",
        ):
            client.post(
                f"/documents/{doc_id}/review", json={"field_path": path, "action": "accept"}
            )
        assert client.get(f"/documents/{doc_id}").json()["suggestion"]["address_matches"] is False

    def test_an_oversized_upload_is_refused_before_it_is_read(
        self,
        newport_property: str,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(documents, "MAX_BYTES", 64)
        response = client.post(
            "/documents",
            data={"kind": "settlement_statement", "property_id": newport_property},
            files={"file": ("big.pdf", pdf_variant("size-guard"), "application/pdf")},
        )
        assert response.status_code == 413
        assert "exceeds" in response.json()["detail"]


class TestExtractionBudgets:
    """The upload cap bounds compressed bytes; these bound the WORK."""

    def build_pdf(self, pages: list[bytes]) -> bytes:
        """A minimal valid PDF with the given raw content streams."""
        objects: list[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        streams = [
            add(b"<< /Length " + str(len(data)).encode() + b" >>\nstream\n" + data + b"\nendstream")
            for data in pages
        ]
        page_numbers = []
        for stream in streams:
            parent = len(objects) + (len(streams) + 1 - len(page_numbers))
            page_numbers.append(
                add(
                    b"<< /Type /Page /Parent " + str(parent).encode() + b" 0 R"
                    b" /MediaBox [0 0 612 792] /Contents " + str(stream).encode() + b" 0 R"
                    b" /Resources << /Font << /F1 " + str(font).encode() + b" 0 R >> >> >>"
                )
            )
        pages_obj = add(
            b"<< /Type /Pages /Kids ["
            + b" ".join(f"{n} 0 R".encode() for n in page_numbers)
            + b"] /Count "
            + str(len(page_numbers)).encode()
            + b" >>"
        )
        catalog = add(b"<< /Type /Catalog /Pages " + str(pages_obj).encode() + b" 0 R >>")
        out = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
        xref_at = len(out)
        out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
        for offset in offsets[1:]:
            out += f"{offset:010d} 00000 n \n".encode()
        out += (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n"
        ).encode()
        return bytes(out)

    def test_a_thousand_page_document_is_refused(self) -> None:
        page = b"BT /F1 10 Tf (x) Tj ET"
        pdf = self.build_pdf([page] * (extraction_parse.MAX_PAGES + 1))
        with pytest.raises(extraction_parse.UnreadableDocument, match="page extraction cap"):
            extraction_parse.extract_lines(pdf)

    def test_a_decompression_bomb_is_refused_by_budget(self) -> None:
        """A compressed upload well under the byte cap can decompress into
        work that pins a worker; the budget is measured after inflation."""
        fat = b"BT /F1 10 Tf (" + b"x" * (extraction_parse.MAX_CONTENT_BYTES + 1) + b") Tj ET"
        with pytest.raises(extraction_parse.UnreadableDocument, match="extraction budget"):
            extraction_parse.extract_lines(self.build_pdf([fat]))

    def test_a_single_space_is_not_a_column_separator(self) -> None:
        # `Total $5.00` is prose, not a two-column charge line.
        assert extraction_parse.match_money_line("Total $5.00") is None
        assert extraction_parse.match_money_line("Total   $5.00") == ("Total", "5.00")

    def test_a_hostile_line_does_not_burn_the_worker(self) -> None:
        """The old label-first regex re-scanned the column gap at every start
        offset — quadratic, and reachable from any upload."""
        started = time.monotonic()
        extraction_parse.parse_settlement([(1, "Label" + " " * 50_000 + "$not-an-amount")])
        assert time.monotonic() - started < 1.0


class TestDomainGuards:
    def test_upload_refuses_oversized_content_below_the_endpoint(
        self, newport_property: str, conn: psycopg.Connection[Any]
    ) -> None:
        """The domain guard stands for callers that never came through HTTP."""
        with pytest.raises(documents.DocumentTooLarge):
            documents.upload(
                conn,
                kind="settlement_statement",
                property_id=newport_property,
                filename="huge.pdf",
                content=b"x" * (documents.MAX_BYTES + 1),
                mime_type="application/pdf",
                document_date=None,
                uploaded_by="tester",
            )

    def test_two_uploads_of_the_same_bytes_race_to_a_409(
        self,
        newport_property: str,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Both requests pass the existence check; the content-addressed
        unique index decides, and the loser gets the same 409."""
        content = pdf_variant("upload-race")
        upload(client, newport_property, content)
        real_execute = psycopg.Connection.execute

        def blind_to_the_existing_row(self: Any, query: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(query, str) and "FROM source_documents WHERE content_hash" in query:
                return real_execute(self, "SELECT NULL::text AS id WHERE FALSE", ())
            return real_execute(self, query, *args, **kwargs)

        monkeypatch.setattr(psycopg.Connection, "execute", blind_to_the_existing_row)
        response = client.post(
            "/documents",
            data={"kind": "settlement_statement", "property_id": newport_property},
            files={"file": ("racer.pdf", content, "application/pdf")},
        )
        assert response.status_code == 409

    def test_an_unsized_upload_still_meets_the_cap(
        self,
        newport_property: str,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When the multipart parser cannot tell us a part's size, the
        domain guard behind it still refuses — as a 413, not a 500."""
        monkeypatch.setattr(documents, "MAX_BYTES", 64)
        # `size` is set per instance by the multipart parser; a part it could
        # not measure arrives as None.
        real_init = UploadFile.__init__

        def unsized(self: UploadFile, *args: Any, **kwargs: Any) -> None:
            real_init(self, *args, **kwargs)
            self.size = None

        monkeypatch.setattr(UploadFile, "__init__", unsized)
        response = client.post(
            "/documents",
            data={"kind": "settlement_statement", "property_id": newport_property},
            files={"file": ("unsized.pdf", pdf_variant("unsized"), "application/pdf")},
        )
        assert response.status_code == 413


class TestContentDisposition:
    """The pure header builder, against input the transport would normally
    encode for us — a hostile non-browser client would not."""

    def test_quotes_and_newlines_never_reach_the_header(self) -> None:
        header = documents.content_disposition('evil";\r\nX-Injected: yes.html', inline=False)
        assert header.startswith("attachment;")
        assert "\r" not in header and "\n" not in header
        # The quote that would have closed the quoted-string early is gone.
        assert 'filename="evil;X-Injected: yes.html"' in header
        assert "filename*=UTF-8''evil%22%3B%0D%0AX-Injected%3A%20yes.html" in header

    def test_a_nameless_document_still_gets_a_name(self) -> None:
        header = documents.content_disposition("\u0000\u007f", inline=True)
        assert header.startswith('inline; filename="document";')


class TestParserEdges:
    """Pure parser branches, no database."""

    def test_an_unparseable_date_arrives_suspect(self) -> None:
        fields = extraction_parse.parse_settlement([(1, "Settlement Date: TBD at recording")])
        (date,) = fields
        assert date.field_path == "settlement.closing_date"
        assert date.normalised_value == "TBD at recording"
        assert date.confidence == extraction_parse.SUSPECT

    def test_a_printed_total_that_disagrees_is_flagged_with_both_sums(self) -> None:
        fields = extraction_parse.parse_settlement(
            [
                (1, "Owner's Title Insurance Policy               $712.00"),
                (2, "Total Capitalizable Closing Costs          $9,999.00"),
            ]
        )
        (costs,) = fields
        assert costs.normalised_value == "712.00"
        assert costs.confidence == extraction_parse.SUSPECT
        assert "9,999.00" in costs.raw_value and "712.00" in costs.raw_value


class TestApply:
    def seed_assessment(self, conn: psycopg.Connection[Any], property_id: str) -> None:
        conn.execute(
            """
            INSERT INTO assessments
              (property_id, jurisdiction_id, tax_year, assessed_land, assessed_total)
            VALUES (%s, %s, 2019, 30000, 160000)
            ON CONFLICT (property_id, jurisdiction_id, tax_year) DO NOTHING
            """,
            (property_id, KY_STATE),
        )
        conn.commit()

    def test_the_acceptance_walk(
        self, newport_property: str, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """Upload the 998 Monmouth closing statement; after review, basis
        fields land in domain rows with document provenance."""
        self.seed_assessment(conn, newport_property)
        detail = upload(client, newport_property, pdf_variant("acceptance"))
        doc_id = detail["id"]
        detail = ratify(client, doc_id)
        suggestion = detail["suggestion"]
        # 189,283 x (30,000 / 160,000) = 35,490.5625 -> banker's cents.
        assert Decimal(suggestion["suggested_land_value"]) == Decimal("35490.56")
        assert "assessment 2019" in suggestion["suggestion_citation"]
        assert "Kentucky" in suggestion["suggestion_citation"]
        response = client.post(
            f"/documents/{doc_id}/apply",
            json={
                "land_value": suggestion["suggested_land_value"],
                "method": f"assessor ratio: {suggestion['suggestion_citation']}",
            },
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert Decimal(result["total_basis"]) == Decimal("189283.00")
        assert Decimal(result["improvement_value"]) == Decimal("153792.44")
        assert result["acquired_on_set"] is True
        assert result["parcel_number_set"] is True
        assert any("loan amount" in note for note in result["notes"])

        allocation = conn.execute(
            "SELECT total_basis, land_value, method, provenance_id FROM price_allocations"
            " WHERE id = %s",
            (result["price_allocation_id"],),
        ).fetchone()
        assert allocation is not None
        assert allocation["total_basis"] == Decimal("189283.00")
        assert "assessor ratio" in allocation["method"]
        provenance = conn.execute(
            "SELECT kind::text AS kind, source_document::text AS source_document,"
            " source_label FROM provenance WHERE id = %s",
            (allocation["provenance_id"],),
        ).fetchone()
        assert provenance == {
            "kind": "document",
            "source_document": doc_id,
            "source_label": "Settlement statement 2019-04-11 (closing.pdf)",
        }
        prop = conn.execute(
            "SELECT acquired_on, parcel_number FROM properties WHERE id = %s",
            (newport_property,),
        ).fetchone()
        assert prop == {
            "acquired_on": dt.date(2019, 4, 11),
            "parcel_number": "999-00-00-037.00",
        }
        event = conn.execute(
            "SELECT amount, category::text AS category, counterparty"
            " FROM ledger_events WHERE id = (SELECT id FROM ledger_events"
            " WHERE event_uuid = %s)",
            (result["ledger_event_uuid"],),
        ).fetchone()
        assert event == {
            "amount": Decimal("-189283.00"),
            "category": "acquisition_cost",
            "counterparty": "Harold Voss and Marlene Voss",
        }
        assert client.get(f"/documents/{doc_id}").json()["status"] == "applied"

    def test_apply_is_exactly_once_and_closes_the_record(
        self, newport_property: str, client: TestClient
    ) -> None:
        detail = upload(client, newport_property, pdf_variant("exactly-once"))
        doc_id = detail["id"]
        ratify(client, doc_id)
        assert (
            client.post(f"/documents/{doc_id}/apply", json={"land_value": "0.00"}).status_code
            == 201
        )
        assert (
            client.post(f"/documents/{doc_id}/apply", json={"land_value": "0.00"}).status_code
            == 409
        )
        assert client.post(f"/documents/{doc_id}/extract").status_code == 409
        assert (
            client.post(
                f"/documents/{doc_id}/review",
                json={"field_path": "settlement.sale_price", "action": "accept"},
            ).status_code
            == 409
        )

    def test_apply_refuses_the_unconfirmed(self, newport_property: str, client: TestClient) -> None:
        detail = upload(client, newport_property, pdf_variant("unconfirmed"))
        response = client.post(f"/documents/{detail['id']}/apply", json={"land_value": "0.00"})
        assert response.status_code == 409
        assert "extracted" in response.json()["detail"]

    def test_apply_refuses_an_overdrawn_allocation(
        self, newport_property: str, client: TestClient
    ) -> None:
        detail = upload(client, newport_property, pdf_variant("overdrawn"))
        doc_id = detail["id"]
        ratify(client, doc_id)
        response = client.post(
            f"/documents/{doc_id}/apply",
            json={"land_value": "189283.01", "personal_property": "0.00"},
        )
        assert response.status_code == 422
        # The rollback reset the gate: a corrected allocation still applies.
        response = client.post(
            f"/documents/{doc_id}/apply",
            json={"land_value": "35000.00", "personal_property": "4000.00"},
        )
        assert response.status_code == 201
        assert Decimal(response.json()["improvement_value"]) == Decimal("150283.00")

    def test_apply_refuses_a_zero_basis(self, newport_property: str, client: TestClient) -> None:
        detail = upload(client, newport_property, pdf_variant("zero-basis"))
        doc_id = detail["id"]
        review(client, doc_id, "settlement.sale_price", "correct", "0.00")
        review(client, doc_id, "settlement.capitalizable_closing_costs", "correct", "0.00")
        review(client, doc_id, "settlement.closing_date", "accept")
        review(client, doc_id, "settlement.property_address", "accept")
        response = client.post(f"/documents/{doc_id}/apply", json={"land_value": "0.00"})
        assert response.status_code == 422
        assert "not a purchase" in response.json()["detail"]

    def test_apply_refuses_multi_property_statements(
        self, newport_property: str, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        detail = upload(client, newport_property, pdf_variant("multi-prop"))
        doc_id = detail["id"]
        ratify(client, doc_id)
        entity = client.post("/entities", json={"name": "Second", "kind": "llc"}).json()
        other = client.post(
            "/properties",
            json={
                "entity_id": entity["id"],
                "label": "Second Property",
                "street_1": "1 Elsewhere Ave",
                "city": "Covington",
                "state": "KY",
                "postal_code": "41011",
                "kind": "single_family",
            },
        ).json()
        conn.execute(
            "INSERT INTO document_properties (document_id, property_id) VALUES (%s, %s)",
            (doc_id, other["id"]),
        )
        conn.commit()
        response = client.post(f"/documents/{doc_id}/apply", json={"land_value": "0.00"})
        assert response.status_code == 422
        assert "2" in response.json()["detail"]

    def test_apply_never_clobbers_recorded_facts(
        self, newport_property: str, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        conn.execute(
            "UPDATE properties SET acquired_on = '2018-01-01', parcel_number = 'OLD-1'"
            " WHERE id = %s",
            (newport_property,),
        )
        conn.commit()
        detail = upload(client, newport_property, pdf_variant("no-clobber"))
        doc_id = detail["id"]
        ratify(client, doc_id)
        result = client.post(f"/documents/{doc_id}/apply", json={"land_value": "0.00"}).json()
        assert result["acquired_on_set"] is False
        assert result["parcel_number_set"] is False
        assert any("acquired_on already 2018-01-01" in note for note in result["notes"])
        assert any("parcel_number already OLD-1" in note for note in result["notes"])
        prop = conn.execute(
            "SELECT acquired_on, parcel_number FROM properties WHERE id = %s",
            (newport_property,),
        ).fetchone()
        assert prop == {"acquired_on": dt.date(2018, 1, 1), "parcel_number": "OLD-1"}

    def test_matching_recorded_facts_pass_silently(
        self, newport_property: str, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        conn.execute(
            "UPDATE properties SET acquired_on = '2019-04-11',"
            " parcel_number = '999-00-00-037.00' WHERE id = %s",
            (newport_property,),
        )
        conn.commit()
        detail = upload(client, newport_property, pdf_variant("facts-match"))
        doc_id = detail["id"]
        ratify(client, doc_id)
        result = client.post(f"/documents/{doc_id}/apply", json={"land_value": "0.00"}).json()
        assert result["acquired_on_set"] is False
        assert result["parcel_number_set"] is False
        assert not any("already" in note for note in result["notes"])

    def test_a_human_can_type_an_entire_statement(
        self, newport_property: str, client: TestClient
    ) -> None:
        """Zero machine fields — a scan the parser cannot read — still walks
        the whole loop on human corrections alone."""
        detail = upload(
            client, newport_property, b"scan placeholder, nothing parseable", filename="scan.txt"
        )
        doc_id = detail["id"]
        assert detail["status"] == "needs_review"
        assert all(f["raw_value"] is None for f in detail["fields"] if f["required"])
        review(client, doc_id, "settlement.closing_date", "correct", "2019-04-11")
        review(client, doc_id, "settlement.sale_price", "correct", "187500")
        review(client, doc_id, "settlement.capitalizable_closing_costs", "correct", "1783")
        after = review(client, doc_id, "settlement.property_address", "correct", "998 Monmouth St")
        assert after["status"] == "confirmed"
        response = client.post(f"/documents/{doc_id}/apply", json={"land_value": "1000.00"})
        assert response.status_code == 201
        assert response.json()["notes"] == []
