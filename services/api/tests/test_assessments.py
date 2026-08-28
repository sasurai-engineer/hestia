"""Assessment records: the notice an owner was mailed, entered two ways.

Issue #46's acceptance, executable: the 2026 notice goes in by hand or by
upload, both leave a provenance behind, and the property's dossier carries
what the body said so the appeal card can render it.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

CAMPBELL_COUNTY = "a0000000-0000-4000-8000-000000000021"
KENTON_COUNTY = "a0000000-0000-4000-8000-000000000022"

FULL_NOTICE = """CAMPBELL COUNTY PROPERTY VALUATION ADMINISTRATOR
Notice to Real Property Owner of Assessment
998 Monmouth St
Tax Year 2026
Notice Date: 04/17/2026
Land                                        $30,000.00
Improvement                                 $130,000.00
Total Value                                 $160,000.00
"""

BARE_NOTICE = """Total Assessed Value                        $150,000
"""

# The Campbell County shape, which is the reason the parser proposes nothing
# when two lines disagree: Fair Cash Value prints 0.00 on an ordinary
# residential parcel while the real figure sits in Total Value. It also prints
# its mailing date twice, which real notices do.
CONFLICTING_NOTICE = """CAMPBELL COUNTY PROPERTY VALUATION ADMINISTRATOR
Tax Year 2026
Notice Date: 04/17/2026
Notice Date: 04/18/2026
Fair Cash Value                             $0.00
Total Value                                 $600,000.00
"""

RAGGED_NOTICE = """Assessor of Property
Parcel ID: 999-99-999
Tax Year: twenty twenty-six
Notice Date: the fifteenth of April
Homestead Exemption                         $46,350.00
Land Value$4.00
Total Value                                 $210,000.00
"""


def make_property(client: TestClient, *, city: str = "Newport", state: str = "KY") -> str:
    entity = client.post("/entities", json={"name": f"{city} LLC", "kind": "llc"}).json()
    return client.post(
        "/properties",
        json={
            "entity_id": entity["id"],
            "label": f"{city} parcel",
            "street_1": "998 Monmouth St",
            "city": city,
            "state": state,
            "postal_code": "41071",
            "kind": "single_family",
        },
    ).json()["id"]


def notice_body(text: str, tag: str) -> bytes:
    """Unique bytes per upload: source_documents dedupes on the content hash
    globally, so two tests uploading the same notice would collide."""
    return f"{text}Reference: {tag}\n".encode()


def upload_notice(client: TestClient, property_id: str, text: str, tag: str) -> dict[str, Any]:
    return client.post(
        "/documents",
        data={"kind": "assessment_notice", "property_id": property_id},
        files={"file": (f"notice-{tag}.txt", notice_body(text, tag), "text/plain")},
    ).json()


def ratify(client: TestClient, doc_id: str, values: dict[str, str]) -> dict[str, Any]:
    """Work the review screen the way a person does.

    Correct what the caller names, then settle everything the parser flagged:
    accept what it proposed, reject what it could not. NOTHING this parser
    emits is CERTAIN — these documents are too various for that — so a notice
    only reaches 'confirmed' once a human has been through every line, which
    is the design rather than an inconvenience.
    """
    for path, value in values.items():
        client.post(
            f"/documents/{doc_id}/review",
            json={"field_path": path, "action": "correct", "value": value},
        )
    for field in client.get(f"/documents/{doc_id}").json()["fields"]:
        if field["reviewed_at"] is not None:
            continue
        settled = client.post(
            f"/documents/{doc_id}/review",
            json={
                "field_path": field["field_path"],
                "action": "accept" if field["normalised_value"] is not None else "reject",
            },
        )
        if settled.status_code == 422:
            # A value the parser preserved verbatim BECAUSE it would not
            # normalise — "the fifteenth of April" — cannot be ratified by one
            # click. That refusal is the feature; the reviewer rejects it.
            client.post(
                f"/documents/{doc_id}/review",
                json={"field_path": field["field_path"], "action": "reject"},
            )
    return client.get(f"/documents/{doc_id}").json()


class TestTheAcceptanceWalk:
    def test_the_2026_notice_by_hand_and_by_upload(self, clean: None, client: TestClient) -> None:
        """Issue #46's acceptance in one test: the same notice, two doors, and
        the only difference in the result is how we know it."""
        typed_property = make_property(client)
        typed = client.post(
            "/assessments",
            json={
                "property_id": typed_property,
                "tax_year": 2026,
                "value_basis": "taxable",
                "assessed_total": "160000.00",
                "assessed_land": "30000.00",
                "assessed_improvement": "130000.00",
                "notice_received_on": "2026-04-17",
            },
        )
        assert typed.status_code == 201, typed.text
        by_hand = typed.json()

        uploaded_property = make_property(client)
        detail = upload_notice(client, uploaded_property, FULL_NOTICE, "acceptance")
        detail = ratify(
            client,
            detail["id"],
            {
                "assessment.tax_year": "2026",
                "assessment.value_basis": "taxable",
                "assessment.assessed_total": "160000.00",
            },
        )
        assert detail["status"] == "confirmed", detail
        applied = client.post(f"/documents/{detail['id']}/apply-assessment", json={})
        assert applied.status_code == 201, applied.text
        by_upload = applied.json()

        for field in ("tax_year", "value_basis", "assessed_total"):
            assert by_hand[field] == by_upload[field]
        assert by_hand["provenance_kind"] == "owner_stated"
        assert by_hand["source_document_id"] is None
        assert by_upload["provenance_kind"] == "document"
        assert by_upload["source_document_id"] == detail["id"]

        # And the appeal card's read: both dossiers carry the row.
        for property_id in (typed_property, uploaded_property):
            view = client.get(f"/properties/{property_id}/dossier").json()
            assert view["assessments"][0]["tax_year"] == 2026
            assert view["assessments"][0]["assessed_total"] == "160000.00"


class TestWhichBodyAssessed:
    def test_an_omitted_body_defaults_to_the_property_s_own(
        self, clean: None, client: TestClient
    ) -> None:
        property_id = make_property(client)
        body = client.post(
            "/assessments",
            json={
                "property_id": property_id,
                "tax_year": 2026,
                "value_basis": "taxable",
                "assessed_total": "160000.00",
            },
        ).json()
        assert body["jurisdiction"] == "Newport"

    def test_the_owner_names_the_county_that_assessed_it(
        self, clean: None, client: TestClient
    ) -> None:
        """Kentucky assesses through the county PVA, and a Newport property
        resolves to Newport — so the owner says which body sent the paper."""
        property_id = make_property(client)
        body = client.post(
            "/assessments",
            json={
                "property_id": property_id,
                "jurisdiction_id": CAMPBELL_COUNTY,
                "tax_year": 2026,
                "value_basis": "taxable",
                "assessed_total": "160000.00",
            },
        )
        assert body.status_code == 201, body.text
        assert body.json()["jurisdiction"] == "Campbell County"

    @pytest.mark.parametrize("named", [KENTON_COUNTY, str(uuid.uuid4())])
    def test_a_body_that_does_not_govern_is_refused(
        self, clean: None, client: TestClient, named: str
    ) -> None:
        """Kenton County is real, adjacent, and does not govern this parcel; a
        made-up id is neither. Both are the same mistake and get one answer."""
        property_id = make_property(client)
        refused = client.post(
            "/assessments",
            json={
                "property_id": property_id,
                "jurisdiction_id": named,
                "tax_year": 2026,
                "value_basis": "taxable",
                "assessed_total": "160000.00",
            },
        )
        assert refused.status_code == 422
        assert "does not govern" in refused.json()["detail"]

    def test_a_property_no_pack_resolves_cannot_record_an_assessment(
        self, clean: None, client: TestClient
    ) -> None:
        """No pack for the state means no body to record against — the
        platform is unconfigured for this address, which is a 503, not a
        malformed request the caller could fix."""
        property_id = make_property(client, city="Indianapolis", state="IN")
        refused = client.post(
            "/assessments",
            json={
                "property_id": property_id,
                "tax_year": 2026,
                "value_basis": "taxable",
                "assessed_total": "160000.00",
            },
        )
        assert refused.status_code == 503
        assert "IN" in refused.json()["detail"]

    def test_an_assessment_for_a_property_that_is_not_there_is_404(
        self, clean: None, client: TestClient
    ) -> None:
        refused = client.post(
            "/assessments",
            json={
                "property_id": str(uuid.uuid4()),
                "tax_year": 2026,
                "value_basis": "taxable",
                "assessed_total": "160000.00",
            },
        )
        assert refused.status_code == 404


class TestWhatTheDomainRefuses:
    def test_one_body_one_year_one_basis(self, clean: None, client: TestClient) -> None:
        property_id = make_property(client)
        payload = {
            "property_id": property_id,
            "tax_year": 2026,
            "value_basis": "taxable",
            "assessed_total": "160000.00",
        }
        assert client.post("/assessments", json=payload).status_code == 201
        again = client.post("/assessments", json=payload)
        assert again.status_code == 409
        assert "already has a taxable 2026" in again.json()["detail"]

    def test_both_bases_of_one_notice_fit(self, clean: None, client: TestClient) -> None:
        """A Tennessee card prints an appraised total beside an assessed one
        for the same parcel and year. The key admits both; that is why the
        basis is in it."""
        property_id = make_property(client)
        for basis, total in (("taxable", "160000.00"), ("market", "640000.00")):
            created = client.post(
                "/assessments",
                json={
                    "property_id": property_id,
                    "tax_year": 2026,
                    "value_basis": basis,
                    "assessed_total": total,
                },
            )
            assert created.status_code == 201, created.text
        view = client.get(f"/properties/{property_id}/dossier").json()
        assert {row["value_basis"] for row in view["assessments"]} == {"market", "taxable"}

    def test_a_land_line_above_the_total_is_refused(self, clean: None, client: TestClient) -> None:
        property_id = make_property(client)
        refused = client.post(
            "/assessments",
            json={
                "property_id": property_id,
                "tax_year": 2026,
                "value_basis": "taxable",
                "assessed_total": "160000.00",
                "assessed_land": "200000.00",
            },
        )
        assert refused.status_code == 422
        assert "exceeds the total" in refused.json()["detail"]

    def test_a_notice_dated_before_its_year_is_refused(
        self, clean: None, client: TestClient
    ) -> None:
        property_id = make_property(client)
        refused = client.post(
            "/assessments",
            json={
                "property_id": property_id,
                "tax_year": 2026,
                "value_basis": "taxable",
                "assessed_total": "160000.00",
                "notice_received_on": "2016-04-15",
            },
        )
        assert refused.status_code == 422
        assert "dated before" in refused.json()["detail"]

    def test_an_improvement_above_the_total_is_accepted(
        self, clean: None, client: TestClient
    ) -> None:
        """Deliberately legal: a total stated net of an exemption its parts
        are gross of. Refusing this would refuse correctly transcribed paper."""
        property_id = make_property(client)
        created = client.post(
            "/assessments",
            json={
                "property_id": property_id,
                "tax_year": 2026,
                "value_basis": "taxable",
                "assessed_total": "160000.00",
                "assessed_improvement": "200000.00",
            },
        )
        assert created.status_code == 201, created.text


class TestTheNoticeDoor:
    def test_a_bare_notice_applies_with_only_a_year_a_basis_and_a_total(
        self, clean: None, client: TestClient
    ) -> None:
        """Whole dollars, no land split, no notice date — the smallest notice
        that still makes a row."""
        property_id = make_property(client)
        detail = upload_notice(client, property_id, BARE_NOTICE, "bare")
        detail = ratify(
            client,
            detail["id"],
            {
                "assessment.tax_year": "2026",
                "assessment.value_basis": "market",
                "assessment.assessed_total": "150000.00",
            },
        )
        applied = client.post(f"/documents/{detail['id']}/apply-assessment", json={})
        assert applied.status_code == 201, applied.text
        row = applied.json()
        assert row["assessed_land"] is None
        assert row["notice_received_on"] is None
        assert row["land_share"] is None
        assert row["value_basis"] == "market"

    def test_a_full_notice_applies_every_line(self, clean: None, client: TestClient) -> None:
        property_id = make_property(client)
        detail = upload_notice(client, property_id, FULL_NOTICE, "full")
        detail = ratify(
            client,
            detail["id"],
            {
                "assessment.tax_year": "2026",
                "assessment.value_basis": "taxable",
                "assessment.assessed_total": "160000.00",
            },
        )
        applied = client.post(f"/documents/{detail['id']}/apply-assessment", json={})
        assert applied.status_code == 201, applied.text
        row = applied.json()
        assert row["assessed_land"] == "30000.00"
        assert row["assessed_improvement"] == "130000.00"
        assert row["notice_received_on"] == "2026-04-17"
        assert Decimal(row["land_share"]) == Decimal("0.187500")

    def test_a_tax_year_typed_as_words_is_refused_at_apply(
        self, clean: None, client: TestClient
    ) -> None:
        """A reviewer may ratify anything the text datatype accepts, so the
        band is enforced at the write — and the refusal leaves the document
        confirmed and appliable rather than half-consumed."""
        property_id = make_property(client)
        detail = upload_notice(client, property_id, RAGGED_NOTICE, "words")
        detail = ratify(
            client,
            detail["id"],
            {
                "assessment.tax_year": "twenty twenty-six",
                "assessment.value_basis": "taxable",
                "assessment.assessed_total": "210000.00",
            },
        )
        refused = client.post(f"/documents/{detail['id']}/apply-assessment", json={})
        assert refused.status_code == 422
        assert "is not a tax year" in refused.json()["detail"]
        assert client.get(f"/documents/{detail['id']}").json()["status"] == "confirmed"

    def test_a_basis_that_is_neither_word_is_refused_at_apply(
        self, clean: None, client: TestClient
    ) -> None:
        """The one field the parser refuses to guess, so it is the one field a
        reviewer can most easily fill with prose."""
        property_id = make_property(client)
        detail = upload_notice(client, property_id, BARE_NOTICE, "basis")
        detail = ratify(
            client,
            detail["id"],
            {
                "assessment.tax_year": "2026",
                "assessment.value_basis": "the big number",
                "assessment.assessed_total": "150000.00",
            },
        )
        refused = client.post(f"/documents/{detail['id']}/apply-assessment", json={})
        assert refused.status_code == 422
        assert "is not a value basis" in refused.json()["detail"]
        assert client.get(f"/documents/{detail['id']}").json()["status"] == "confirmed"

    def test_applying_the_same_notice_twice_is_a_409(
        self, clean: None, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        property_id = make_property(client)
        detail = upload_notice(client, property_id, BARE_NOTICE, "twice")
        detail = ratify(
            client,
            detail["id"],
            {
                "assessment.tax_year": "2026",
                "assessment.value_basis": "market",
                "assessment.assessed_total": "150000.00",
            },
        )
        assert (
            client.post(f"/documents/{detail['id']}/apply-assessment", json={}).status_code == 201
        )
        again = client.post(f"/documents/{detail['id']}/apply-assessment", json={})
        assert again.status_code == 409
        rows = conn.execute(
            "SELECT count(*) AS n FROM assessments WHERE property_id = %s", (property_id,)
        ).fetchone()
        assert rows is not None and rows["n"] == 1

    def test_an_unreviewed_notice_cannot_be_applied(self, clean: None, client: TestClient) -> None:
        property_id = make_property(client)
        detail = upload_notice(client, property_id, FULL_NOTICE, "unreviewed")
        refused = client.post(f"/documents/{detail['id']}/apply-assessment", json={})
        assert refused.status_code == 409
        assert "confirmed" in refused.json()["detail"]

    def test_applying_a_notice_that_is_not_there_is_404(
        self, clean: None, client: TestClient
    ) -> None:
        refused = client.post(f"/documents/{uuid.uuid4()}/apply-assessment", json={})
        assert refused.status_code == 404

    def test_a_notice_for_a_year_already_typed_is_a_409(
        self, clean: None, client: TestClient
    ) -> None:
        """The collision an owner will actually hit: they type the notice, then
        upload the same paper. The document survives, still appliable."""
        property_id = make_property(client)
        client.post(
            "/assessments",
            json={
                "property_id": property_id,
                "tax_year": 2026,
                "value_basis": "market",
                "assessed_total": "150000.00",
            },
        )
        detail = upload_notice(client, property_id, BARE_NOTICE, "collide")
        detail = ratify(
            client,
            detail["id"],
            {
                "assessment.tax_year": "2026",
                "assessment.value_basis": "market",
                "assessment.assessed_total": "150000.00",
            },
        )
        refused = client.post(f"/documents/{detail['id']}/apply-assessment", json={})
        assert refused.status_code == 409
        assert client.get(f"/documents/{detail['id']}").json()["status"] == "confirmed"

    def test_a_notice_linked_to_two_properties_is_refused(
        self, clean: None, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        first = make_property(client)
        second = make_property(client, city="Bellevue")
        detail = upload_notice(client, first, BARE_NOTICE, "twoprops")
        detail = ratify(
            client,
            detail["id"],
            {
                "assessment.tax_year": "2026",
                "assessment.value_basis": "market",
                "assessment.assessed_total": "150000.00",
            },
        )
        conn.execute(
            "INSERT INTO document_properties (document_id, property_id) VALUES (%s, %s)",
            (detail["id"], second),
        )
        conn.commit()
        refused = client.post(f"/documents/{detail['id']}/apply-assessment", json={})
        assert refused.status_code == 422
        assert "one notice assesses one parcel" in refused.json()["detail"]


class TestTheTwoDoorsDoNotCross:
    def test_a_notice_does_not_apply_as_a_settlement_statement(
        self, clean: None, client: TestClient
    ) -> None:
        """Before #46 this reached a KeyError and escaped as a 500, because
        nothing but a settlement statement could ever reach 'confirmed'."""
        property_id = make_property(client)
        detail = upload_notice(client, property_id, BARE_NOTICE, "wrongdoor")
        detail = ratify(
            client,
            detail["id"],
            {
                "assessment.tax_year": "2026",
                "assessment.value_basis": "market",
                "assessment.assessed_total": "150000.00",
            },
        )
        refused = client.post(f"/documents/{detail['id']}/apply", json={"land_value": "1000.00"})
        assert refused.status_code == 422
        assert "does not apply as a settlement statement" in refused.json()["detail"]
        assert client.get(f"/documents/{detail['id']}").json()["status"] == "confirmed"


class TestTheDossierRead:
    def test_the_dossier_carries_the_assessments_it_knows(
        self, clean: None, client: TestClient
    ) -> None:
        property_id = make_property(client)
        for year, total, land in ((2025, "150000.00", None), (2026, "160000.00", "30000.00")):
            payload: dict[str, Any] = {
                "property_id": property_id,
                "jurisdiction_id": CAMPBELL_COUNTY,
                "tax_year": year,
                "value_basis": "taxable",
                "assessed_total": total,
            }
            if land is not None:
                payload["assessed_land"] = land
            assert client.post("/assessments", json=payload).status_code == 201
        # A third row, same year, DIFFERENT body: not a comparison, so it must
        # not become one.
        client.post(
            "/assessments",
            json={
                "property_id": property_id,
                "tax_year": 2026,
                "value_basis": "taxable",
                "assessed_total": "155000.00",
            },
        )

        view = client.get(f"/properties/{property_id}/dossier").json()
        rows = {(r["tax_year"], r["jurisdiction"]): r for r in view["assessments"]}
        assert view["assessments"][0]["tax_year"] == 2026

        current = rows[(2026, "Campbell County")]
        assert current["prior_tax_year"] == 2025
        assert Decimal(current["change_from_prior"]) == Decimal("10000.00")
        assert Decimal(current["land_share"]) == Decimal("0.187500")
        assert current["provenance_kind"] == "owner_stated"

        assert rows[(2025, "Campbell County")]["land_share"] is None
        # Newport's own 2026 row has no prior year from Newport.
        assert rows[(2026, "Newport")]["prior_tax_year"] is None
        assert rows[(2026, "Newport")]["change_from_prior"] is None

    def test_the_chain_carries_the_ids_a_picker_needs(
        self, clean: None, client: TestClient
    ) -> None:
        property_id = make_property(client)
        view = client.get(f"/properties/{property_id}/dossier").json()
        chain = {link["level"]: link for link in view["jurisdiction_chain"]}
        assert chain["county"]["id"] == CAMPBELL_COUNTY
        assert chain["county"]["name"] == "Campbell County"


class TestWhatThePaperActuallyLooksLike:
    def test_two_lines_that_disagree_propose_nothing(self, clean: None, client: TestClient) -> None:
        """Campbell County's own records print Fair Cash Value as 0.00 beside
        a Total Value of 600,000 on an ordinary house. Proposing the first
        reading would let a reviewer ratify zero with one click, so the parser
        shows both and proposes neither — and the review path refuses to
        accept a field with no proposed value."""
        property_id = make_property(client)
        detail = upload_notice(client, property_id, CONFLICTING_NOTICE, "conflict")
        total = next(f for f in detail["fields"] if f["field_path"] == "assessment.assessed_total")
        assert total["normalised_value"] is None
        assert "Fair Cash Value $0.00" in total["raw_value"]
        assert "Total Value $600,000.00" in total["raw_value"]
        refused = client.post(
            f"/documents/{detail['id']}/review",
            json={"field_path": "assessment.assessed_total", "action": "accept"},
        )
        assert refused.status_code == 422

        # Only the FIRST notice date is taken; the second is not a new fact.
        notice_date = next(
            f for f in detail["fields"] if f["field_path"] == "assessment.notice_date"
        )
        assert notice_date["normalised_value"] == "2026-04-17"

    def test_a_settlement_statement_does_not_apply_as_a_notice(
        self, clean: None, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """The mirror of the other door's guard. Both refusals leave the
        document confirmed, because the gate rolls back with the refusal."""
        property_id = make_property(client)
        document_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO source_documents (id, kind, filename, content_hash, status)
            VALUES (%s, 'settlement_statement', 'closing.pdf', %s, 'confirmed')
            """,
            (document_id, "c" * 64),
        )
        conn.execute(
            "INSERT INTO document_properties (document_id, property_id) VALUES (%s, %s)",
            (document_id, property_id),
        )
        conn.commit()
        refused = client.post(f"/documents/{document_id}/apply-assessment", json={})
        assert refused.status_code == 422
        assert "is not an assessment notice" in refused.json()["detail"]
        status = conn.execute(
            "SELECT status::text AS status FROM source_documents WHERE id = %s",
            (document_id,),
        ).fetchone()
        assert status is not None and status["status"] == "confirmed"

    def test_an_absurd_land_line_is_refused_not_a_500(
        self, clean: None, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """An OPTIONAL money field that never needed review never passed the
        review path's bound either. Today's parser marks nothing certain, but
        the model seam behind the same registry will, and unbounded this
        reached the client as a psycopg NumericValueOutOfRange 500 — after the
        gate had already flipped the document."""
        property_id = make_property(client)
        detail = upload_notice(client, property_id, BARE_NOTICE, "absurd")
        detail = ratify(
            client,
            detail["id"],
            {
                "assessment.tax_year": "2026",
                "assessment.value_basis": "market",
                "assessment.assessed_total": "150000.00",
            },
        )
        assert detail["status"] == "confirmed", detail
        # AFTER review, and needing none: this is the shape a certain-enough
        # extractor produces, and the one that never meets the review path's
        # own bound.
        conn.execute(
            """
            INSERT INTO extracted_fields
              (document_id, field_path, raw_value, normalised_value, confidence,
               needs_review, model_id)
            VALUES (%s, 'assessment.assessed_land', '$1e20', %s, 1, FALSE, 'test')
            ON CONFLICT (document_id, field_path) DO UPDATE
              SET normalised_value = EXCLUDED.normalised_value,
                  accepted_value = NULL, reviewed_at = NULL, reviewed_by = NULL,
                  needs_review = FALSE, confidence = 1
            """,
            (detail["id"], "9" * 20),
        )
        conn.commit()
        refused = client.post(f"/documents/{detail['id']}/apply-assessment", json={})
        assert refused.status_code == 422
        assert "exceeds the largest amount" in refused.json()["detail"]
