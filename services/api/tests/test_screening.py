"""Screening decisions and the notice a denial owes.

The acceptance criteria of issue #3, made executable: record a denial and the
deadline appears with its citation; record the sent date and it resolves. The
whole workflow is FCRA-complete with no provider at all.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from hestia_api import screening


@pytest.fixture
def applicant(newport_property: str, client: TestClient) -> dict[str, str]:
    resident = client.post("/residents", json={"full_name": "A. Applicant"}).json()
    return {"property": newport_property, "resident": resident["id"]}


def open_request(client: TestClient, world: dict[str, str], **overrides: Any) -> dict[str, Any]:
    body = {
        "resident_id": world["resident"],
        "property_id": world["property"],
        "requested_on": "2026-08-01",
        **overrides,
    }
    response = client.post("/screening", json=body)
    assert response.status_code == 201, response.text
    return response.json()


class TestTheAcceptanceWalk:
    def test_a_denial_raises_the_notice_and_sending_it_resolves(
        self, applicant: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        request = open_request(client, applicant)
        assert request["decision"] == "pending"
        assert request["adverse_action_required"] is False
        assert request["notice_contents"] == []

        decided = client.post(
            f"/screening/{request['id']}/decision",
            json={
                "decision": "denied",
                "decided_on": "2026-08-05",
                "decision_basis": "income below the posted standard",
                "based_on_consumer_report": True,
            },
        ).json()
        assert decided["adverse_action_required"] is True
        # The letter's required contents come from the server, cited.
        assert len(decided["notice_contents"]) == len(screening.NOTICE_CONTENTS)
        assert any("free copy" in item["requirement"] for item in decided["notice_contents"])
        assert all("1681m" in item["citation"] for item in decided["notice_contents"])
        assert "1681m(a)" in decided["citation"]

        client.post("/sweep/deadlines?as_of=2026-08-06")
        deadline = conn.execute(
            """
            SELECT kind::text AS kind, due_on, status::text AS status, citation, note
            FROM deadlines WHERE screening_request_id = %s
            """,
            (request["id"],),
        ).fetchone()
        assert deadline is not None
        assert deadline["kind"] == "adverse_action_notice"
        # Dated to the decision: the statute sets no day count, so none is invented.
        assert deadline["due_on"] == dt.date(2026, 8, 5)
        assert deadline["status"] == "upcoming"
        assert "1681m(a)" in deadline["citation"]
        assert "A. Applicant" in deadline["note"]

        sent = client.post(
            f"/screening/{request['id']}/adverse-action", json={"sent_on": "2026-08-07"}
        ).json()
        assert sent["adverse_action_sent_on"] == "2026-08-07"
        assert sent["notice_contents"] == []  # nothing left owed

        resolved = conn.execute(
            "SELECT status::text AS status, completed_on FROM deadlines"
            " WHERE screening_request_id = %s",
            (request["id"],),
        ).fetchone()
        assert resolved["status"] == "done"
        assert resolved["completed_on"] == dt.date(2026, 8, 7)
        # The resident's own summary field, carried since module 003.
        assert conn.execute(
            "SELECT adverse_action_sent_on FROM residents WHERE id = %s",
            (applicant["resident"],),
        ).fetchone()["adverse_action_sent_on"] == dt.date(2026, 8, 7)

        # Re-sweeping raises nothing new: the duty is discharged.
        client.post("/sweep/deadlines?as_of=2026-08-08")
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM deadlines WHERE screening_request_id = %s",
                (request["id"],),
            ).fetchone()["n"]
            == 1
        )

    def test_two_applicants_refused_on_one_day_are_two_notices(
        self, applicant: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """Without its own anchor the second notice would collapse into the
        first and go unsent."""
        second = client.post("/residents", json={"full_name": "B. Applicant"}).json()
        ids = []
        for resident in (applicant["resident"], second["id"]):
            request = open_request(client, applicant, resident_id=resident)
            client.post(
                f"/screening/{request['id']}/decision",
                json={
                    "decision": "denied",
                    "decided_on": "2026-08-05",
                    "based_on_consumer_report": True,
                },
            )
            ids.append(request["id"])
        client.post("/sweep/deadlines?as_of=2026-08-06")
        rows = conn.execute(
            "SELECT screening_request_id::text AS sid FROM deadlines"
            " WHERE kind::text = 'adverse_action_notice' AND due_on = '2026-08-05'"
        ).fetchall()
        assert sorted(r["sid"] for r in rows) == sorted(ids)


class TestWhenTheDutyAttaches:
    def test_a_conditional_approval_on_a_report_is_adverse_action(
        self, applicant: dict[str, str], client: TestClient
    ) -> None:
        """A larger deposit because of a report is exactly what
        15 U.S.C. 1681a(k)(1)(B)(ii) is about."""
        request = open_request(client, applicant)
        decided = client.post(
            f"/screening/{request['id']}/decision",
            json={
                "decision": "conditional",
                "decided_on": "2026-08-05",
                "decision_basis": "approved with a double deposit",
                "based_on_consumer_report": True,
            },
        ).json()
        assert decided["adverse_action_required"] is True

    def test_a_denial_on_the_owner_s_own_judgement_owes_nothing(
        self, applicant: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """Both halves of s.615(a) or it does not attach: no report, no notice."""
        request = open_request(client, applicant)
        decided = client.post(
            f"/screening/{request['id']}/decision",
            json={
                "decision": "denied",
                "decided_on": "2026-08-05",
                "decision_basis": "the unit was let to an earlier applicant",
                "based_on_consumer_report": False,
            },
        ).json()
        assert decided["adverse_action_required"] is False
        assert decided["citation"] is None
        client.post("/sweep/deadlines?as_of=2026-08-06")
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM deadlines WHERE screening_request_id = %s",
                (request["id"],),
            ).fetchone()["n"]
            == 0
        )

    def test_an_approval_owes_nothing_and_cannot_send_one(
        self, applicant: dict[str, str], client: TestClient
    ) -> None:
        request = open_request(client, applicant)
        client.post(
            f"/screening/{request['id']}/decision",
            json={
                "decision": "approved",
                "decided_on": "2026-08-05",
                "based_on_consumer_report": True,
            },
        )
        response = client.post(f"/screening/{request['id']}/adverse-action", json={})
        assert response.status_code == 422
        assert "s.615(a) attaches only when" in response.json()["detail"]

    def test_a_withdrawal_is_not_adverse_action(
        self, applicant: dict[str, str], client: TestClient
    ) -> None:
        request = open_request(client, applicant)
        decided = client.post(
            f"/screening/{request['id']}/decision",
            json={
                "decision": "withdrawn",
                "decided_on": "2026-08-05",
                "based_on_consumer_report": True,
            },
        ).json()
        assert decided["adverse_action_required"] is False


class TestRefusals:
    def test_a_decision_is_recorded_once(
        self, applicant: dict[str, str], client: TestClient
    ) -> None:
        request = open_request(client, applicant)
        assert (
            client.post(
                f"/screening/{request['id']}/decision",
                json={"decision": "approved", "decided_on": "2026-08-05"},
            ).status_code
            == 200
        )
        again = client.post(
            f"/screening/{request['id']}/decision",
            json={"decision": "denied", "decided_on": "2026-08-06"},
        )
        assert again.status_code == 409
        assert "already approved" in again.json()["detail"]

    def test_a_notice_is_sent_once(self, applicant: dict[str, str], client: TestClient) -> None:
        request = open_request(client, applicant)
        client.post(
            f"/screening/{request['id']}/decision",
            json={
                "decision": "denied",
                "decided_on": "2026-08-05",
                "based_on_consumer_report": True,
            },
        )
        assert (
            client.post(
                f"/screening/{request['id']}/adverse-action", json={"sent_on": "2026-08-07"}
            ).status_code
            == 200
        )
        again = client.post(
            f"/screening/{request['id']}/adverse-action", json={"sent_on": "2026-08-08"}
        )
        assert again.status_code == 409
        assert "already sent on 2026-08-07" in again.json()["detail"]

    def test_a_decision_cannot_precede_the_application(
        self, applicant: dict[str, str], client: TestClient
    ) -> None:
        request = open_request(client, applicant)
        response = client.post(
            f"/screening/{request['id']}/decision",
            json={"decision": "approved", "decided_on": "2026-07-01"},
        )
        assert response.status_code == 422
        assert "cannot precede the application" in response.json()["detail"]

    def test_a_notice_cannot_precede_its_decision(
        self, applicant: dict[str, str], client: TestClient
    ) -> None:
        request = open_request(client, applicant)
        client.post(
            f"/screening/{request['id']}/decision",
            json={
                "decision": "denied",
                "decided_on": "2026-08-05",
                "based_on_consumer_report": True,
            },
        )
        response = client.post(
            f"/screening/{request['id']}/adverse-action", json={"sent_on": "2026-08-01"}
        )
        assert response.status_code == 422
        assert "cannot precede the decision" in response.json()["detail"]

    def test_unknown_things_are_404_and_a_foreign_unit_is_422(
        self, applicant: dict[str, str], client: TestClient
    ) -> None:
        ghost = "00000000-0000-4000-8000-000000000000"
        assert client.get(f"/screening/{ghost}").status_code == 404
        assert (
            client.post(f"/screening/{ghost}/decision", json={"decision": "approved"}).status_code
            == 404
        )
        assert client.post(f"/screening/{ghost}/adverse-action", json={}).status_code == 404
        assert (
            client.post(
                "/screening", json={"resident_id": ghost, "property_id": applicant["property"]}
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/screening", json={"resident_id": applicant["resident"], "property_id": ghost}
            ).status_code
            == 404
        )
        entity = client.post("/entities", json={"name": "Elsewhere", "kind": "llc"}).json()
        other = client.post(
            "/properties",
            json={
                "entity_id": entity["id"],
                "label": "Elsewhere",
                "street_1": "9 Elsewhere Ave",
                "city": "Newport",
                "state": "KY",
                "postal_code": "41071",
                "kind": "single_family",
            },
        ).json()
        unit = client.post("/units", json={"property_id": other["id"], "label": "Z"}).json()
        response = client.post(
            "/screening",
            json={
                "resident_id": applicant["resident"],
                "property_id": applicant["property"],
                "unit_id": unit["id"],
            },
        )
        assert response.status_code == 422


class TestQueue:
    def test_the_queue_answers_who_is_still_owed_a_letter(
        self, applicant: dict[str, str], client: TestClient
    ) -> None:
        owed = open_request(client, applicant)
        client.post(
            f"/screening/{owed['id']}/decision",
            json={
                "decision": "denied",
                "decided_on": "2026-08-05",
                "based_on_consumer_report": True,
            },
        )
        settled = open_request(client, applicant)
        client.post(
            f"/screening/{settled['id']}/decision",
            json={"decision": "approved", "decided_on": "2026-08-05"},
        )
        queue = client.get("/screening?notice_owed=true").json()
        assert [row["id"] for row in queue] == [owed["id"]]
        by_resident = client.get(f"/screening?resident_id={applicant['resident']}").json()
        assert len(by_resident) == 2
        by_property = client.get(f"/screening?property_id={applicant['property']}").json()
        assert len(by_property) == 2
        assert client.get(f"/screening/{owed['id']}").json()["resident_name"] == "A. Applicant"

    def test_a_request_can_name_its_unit_and_provider(
        self, applicant: dict[str, str], client: TestClient
    ) -> None:
        unit = client.post(
            "/units", json={"property_id": applicant["property"], "label": "B"}
        ).json()
        request = open_request(
            client, applicant, unit_id=unit["id"], provider="transunion_shareable", notes="walk-in"
        )
        assert request["unit_label"] == "B"
        assert request["provider"] == "transunion_shareable"
        assert request["notes"] == "walk-in"
