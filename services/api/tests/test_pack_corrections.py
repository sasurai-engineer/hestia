"""The correction drill: a rule that turns out to be wrong, end to end.

A pack is applied-once and its bytes never change, so a wrong rule is
corrected by SUPERSEDING it or CLOSED by effective_to. Both filters have been
in the resolver since the packs shipped and neither had ever been exercised
through the sweep — the carried finding this suite closes. The point is not
that the SQL works; it is that a correction reaches the calendar and the
coverage report, which is where an owner would read it.

The supersede half runs against the REAL correction (seed/952, issue #97):
Ohio's appeal instructions asserted a filing window ORC 5715.19(A) does not
state. The effective_to half runs in a sandboxed synthetic state, because
nothing in the packs has legitimately expired yet and inventing an expiry for
a real jurisdiction would be seeding a fact nobody established.
"""

from __future__ import annotations

from typing import Any

import psycopg
from fastapi.testclient import TestClient

OHIO = "a0000000-0039-4000-8000-000000000010"


def make_property(client: TestClient, *, city: str, state: str, postal: str) -> str:
    entity = client.post("/entities", json={"name": f"{city} LLC", "kind": "llc"}).json()
    return client.post(
        "/properties",
        json={
            "entity_id": entity["id"],
            "label": f"{city} parcel",
            "street_1": "1 Main St",
            "city": city,
            "state": state,
            "postal_code": postal,
            "kind": "single_family",
        },
    ).json()["id"]


def swept_note(conn: psycopg.Connection[Any], property_id: str) -> tuple[str, str]:
    row = conn.execute(
        """
        SELECT note, citation FROM deadlines
        WHERE property_id = %s AND kind = 'assessment_appeal_window'
        ORDER BY due_on LIMIT 1
        """,
        (property_id,),
    ).fetchone()
    assert row is not None, "the sweep emitted no appeal window"
    return row["note"], row["citation"]


class TestTheShippedCorrection:
    def test_the_superseded_row_survives_and_is_excluded(
        self, clean: None, conn: psycopg.Connection[Any]
    ) -> None:
        """A correction does not delete history. What the pack said in March
        is still answerable; it is simply no longer resolved."""
        rows = conn.execute(
            """
            SELECT id::text, value_text, citation, superseded_by::text AS superseded_by
            FROM jurisdiction_rules
            WHERE jurisdiction_id = %s AND code = 'appeal.instructions'
            ORDER BY superseded_by NULLS LAST
            """,
            (OHIO,),
        ).fetchall()
        assert len(rows) == 2, "expected the corrected row and the row it replaced"
        current = next(r for r in rows if r["superseded_by"] is None)
        retired = next(r for r in rows if r["superseded_by"] is not None)

        # The old row still says what it said, and points at its replacement.
        assert "between January 1 and March 31" in retired["value_text"]
        assert retired["citation"] == "ORC 5715.19(A)(1)" or retired["citation"].endswith(
            "5715.19(A)"
        )
        assert retired["superseded_by"] == current["id"]

        # The correction carries the subsection that actually says it, and no
        # longer claims a statutory opening date.
        assert current["citation"] == "ORC 5715.19(A)(1)"
        assert "whichever is later" in current["value_text"]
        assert "conventionally" in current["value_text"]

    def test_the_correction_reaches_the_calendar(
        self, clean: None, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """The half that matters. A corrected rule is worth nothing until the
        deadline an owner reads carries the new words."""
        property_id = make_property(client, city="Cincinnati", state="OH", postal="45202")
        client.post("/sweep/deadlines?as_of=2026-06-01")
        note, citation = swept_note(conn, property_id)
        assert "whichever is later" in note
        assert "between January 1 and March 31" not in note
        assert "5715.19" in citation

    def test_the_correction_reaches_the_coverage_report(
        self, clean: None, client: TestClient
    ) -> None:
        property_id = make_property(client, city="Cincinnati", state="OH", postal="45202")
        body = client.get("/coverage/jurisdictions?as_of=2026-06-01").json()
        found = next(p for p in body["properties"] if p["property_id"] == property_id)
        appeal = found["domains"]["assessment_appeal"]
        assert appeal["status"] == "covered"
        assert appeal["source"] == "Ohio"

    def test_the_eligibility_bar_the_pack_never_carried(
        self, clean: None, conn: psycopg.Connection[Any]
    ) -> None:
        """Additive rather than corrective, and shipped in the same file
        because it is the same reading of the same statute."""
        row = conn.execute(
            """
            SELECT value_text, citation FROM jurisdiction_rules
            WHERE jurisdiction_id = %s AND code = 'appeal.second_complaint_barred'
              AND superseded_by IS NULL
            """,
            (OHIO,),
        ).fetchone()
        assert row is not None
        assert row["citation"] == "ORC 5715.19(A)(2)"
        assert "arm's-length sale" in row["value_text"]


def plant_pack(conn: psycopg.Connection[Any], state: str, name: str) -> str:
    """A synthetic pack to correct without touching a real jurisdiction.

    Each drill gets its OWN state, and that is not fastidiousness. A
    correction is by construction irreversible — jurisdiction_rules is
    append-only in practice and `clean` does not wipe it — so two drills
    sharing one pack means the second one starts from whatever the first
    corrected. That is the same property this whole suite exists to
    demonstrate, met from the inconvenient side.
    """
    if (
        conn.execute(
            "SELECT 1 AS x FROM jurisdictions WHERE state = %s AND level = 'state'",
            (state,),
        ).fetchone()
        is None
    ):
        conn.execute(
            """
            WITH state_row AS (
              INSERT INTO jurisdictions (level, name, state, parent_id)
              SELECT 'state', %s, %s, id FROM jurisdictions
              WHERE level = 'federal' RETURNING id
            )
            INSERT INTO jurisdictions (level, name, state, parent_id)
            SELECT 'municipality', %s, %s, id FROM state_row
            """,
            (name, state, f"{name}ville", state),
        )
        conn.execute(
            """
            INSERT INTO jurisdiction_rules
              (jurisdiction_id, domain, code, value_text, citation, effective_from)
            SELECT id, 'assessment_appeal', 'appeal.window.calendar',
                   'us-ky.open-inspection', %s, DATE '2000-01-01'
            FROM jurisdictions WHERE state = %s AND level = 'state'
            """,
            (f"{state} Rev. Stat. 1.1 (as first written)", state),
        )
        conn.execute(
            """
            INSERT INTO jurisdiction_rules
              (jurisdiction_id, domain, code, value_text, citation, effective_from)
            SELECT id, 'assessment_appeal', 'appeal.instructions',
                   'the original instructions', %s, DATE '2000-01-01'
            FROM jurisdictions WHERE state = %s AND level = 'state'
            """,
            (f"{state} Rev. Stat. 1.2", state),
        )
        conn.commit()
    row = conn.execute(
        "SELECT id::text FROM jurisdictions WHERE state = %s AND level = 'state'", (state,)
    ).fetchone()
    assert row is not None
    return str(row["id"])


class TestTheDrill:
    def test_a_supersede_moves_the_sweep_from_one_rule_to_the_other(
        self, clean: None, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """The mechanism observed dynamically: sweep, correct, sweep again."""
        plant_pack(conn, "QD", "Quadd")
        property_id = make_property(client, city="Quaddville", state="QD", postal="00000")
        client.post("/sweep/deadlines?as_of=2026-06-01")
        note, _ = swept_note(conn, property_id)
        assert note == "the original instructions"

        conn.execute(
            """
            WITH corrected AS (
              INSERT INTO jurisdiction_rules
                (jurisdiction_id, domain, code, value_text, citation, effective_from)
              SELECT jurisdiction_id, domain, code, 'the corrected instructions',
                     'QD Rev. Stat. 1.2 (as corrected)', effective_from
              FROM jurisdiction_rules
              WHERE code = 'appeal.instructions' AND superseded_by IS NULL
                AND jurisdiction_id = (SELECT id FROM jurisdictions
                                        WHERE state = 'QD' AND level = 'state')
              RETURNING id, jurisdiction_id, code, effective_from
            )
            UPDATE jurisdiction_rules superseded SET superseded_by = corrected.id
            FROM corrected
            WHERE superseded.jurisdiction_id = corrected.jurisdiction_id
              AND superseded.code = corrected.code
              AND superseded.effective_from = corrected.effective_from
              AND superseded.superseded_by IS NULL
              AND superseded.id <> corrected.id
            """
        )
        conn.commit()

        # The deadline the sweep already wrote is not rewritten in place; the
        # next sweep is what carries the correction forward.
        conn.execute("DELETE FROM deadlines WHERE property_id = %s", (property_id,))
        conn.commit()
        client.post("/sweep/deadlines?as_of=2026-06-01")
        note, citation = swept_note(conn, property_id)
        assert note == "the corrected instructions"
        # A correction is SCOPED to the code it corrects. The deadline's
        # citation comes from appeal.window.calendar, which nobody touched,
        # and it must not have moved: a supersede that quietly disturbed a
        # neighbouring rule would be far worse than the error it fixed.
        assert citation == "QD Rev. Stat. 1.1 (as first written)"

        # And exactly one row is open, which is what the twin guard protects.
        open_rows = conn.execute(
            """
            SELECT count(*) AS n FROM jurisdiction_rules r
            JOIN jurisdictions j ON j.id = r.jurisdiction_id
            WHERE j.state = 'QD' AND r.code = 'appeal.instructions'
              AND r.superseded_by IS NULL
            """
        ).fetchone()
        assert open_rows is not None and open_rows["n"] == 1

    def test_a_rule_closed_by_effective_to_stops_resolving(
        self, clean: None, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        """The other half. An AMENDMENT closes the old rule on the day the new
        one starts, rather than pretending the old one was never right."""
        state_id = plant_pack(conn, "QE", "Quenn")
        property_id = make_property(client, city="Quennville", state="QE", postal="00000")
        conn.execute(
            """
            UPDATE jurisdiction_rules SET effective_to = DATE '2026-01-01'
            WHERE jurisdiction_id = %s AND code = 'appeal.instructions'
              AND superseded_by IS NULL
            """,
            (state_id,),
        )
        conn.execute(
            """
            INSERT INTO jurisdiction_rules
              (jurisdiction_id, domain, code, value_text, citation, effective_from)
            VALUES (%s, 'assessment_appeal', 'appeal.instructions',
                    'the instructions after the amendment',
                    'QE Rev. Stat. 1.2 (2026 amendment)', DATE '2026-01-01')
            """,
            (state_id,),
        )
        conn.commit()

        # Before the amendment takes effect, the old rule still governs.
        client.post("/sweep/deadlines?as_of=2025-06-01")
        note, _ = swept_note(conn, property_id)
        assert note == "the original instructions"

        conn.execute("DELETE FROM deadlines WHERE property_id = %s", (property_id,))
        conn.commit()
        client.post("/sweep/deadlines?as_of=2026-06-01")
        note, citation = swept_note(conn, property_id)
        assert note == "the instructions after the amendment"
        # Same scoping check: closing one code left the calendar rule alone.
        assert citation == "QE Rev. Stat. 1.1 (as first written)"
        # And the closed row is still there, answering what governed in 2025.
        historic = conn.execute(
            """
            SELECT value_text FROM jurisdiction_rules
            WHERE jurisdiction_id = %s AND code = 'appeal.instructions'
              AND effective_to IS NOT NULL
            """,
            (state_id,),
        ).fetchone()
        assert historic is not None
        assert historic["value_text"] == "the original instructions"

    def test_a_closed_rule_and_its_successor_are_not_open_twins(
        self, clean: None, conn: psycopg.Connection[Any]
    ) -> None:
        """The guard the correction workflow must not trip. Two rules for one
        code are fine when their effective windows do not overlap; two OPEN
        rows at the same effective_from would make resolution arbitrary."""
        twins = conn.execute(
            """
            SELECT count(*) AS n FROM (
              SELECT jurisdiction_id, domain, code, effective_from
              FROM jurisdiction_rules WHERE superseded_by IS NULL
              GROUP BY jurisdiction_id, domain, code, effective_from
              HAVING count(*) > 1
            ) ambiguous
            """
        ).fetchone()
        assert twins is not None and twins["n"] == 0
