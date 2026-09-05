"""The correspondent channel (issue #38): one message per (deadline, step),
the covenant's voice on every message, the interrupt class reserved, and a
ledger that records even when no wire exists."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from hestia_api import calendar, notify


@pytest.fixture
def world(clean: None, client: TestClient, conn: psycopg.Connection[Any]) -> dict[str, str]:
    entity_id = client.post("/entities", json={"name": "N38", "kind": "llc"}).json()["id"]
    property_id = client.post(
        "/properties",
        json={
            "entity_id": entity_id,
            "label": "monmouth",
            "street_1": "998 Monmouth St",
            "city": "Newport",
            "state": "KY",
            "postal_code": "41071",
            "kind": "single_family",
        },
    ).json()["id"]
    deadline_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO deadlines (id, kind, due_on, window_opens_on, property_id, citation, note)
        VALUES (%s, 'tax_payment_due', '2026-10-31', NULL, %s,
                'KRS s.91A.070(2); City of Newport Finance/Taxes page',
                'city bills are payable on or before October 31')
        """,
        (deadline_id, property_id),
    )
    conn.commit()
    return {"entity": entity_id, "property": property_id, "deadline": deadline_id}


class TestReminderTwin:
    def test_anchors_match_the_ts_engine(self) -> None:
        due = dt.date(2026, 10, 31)
        # Deduplicated, ascending — the TS twin's documented behavior.
        assert calendar.reminder_schedule(due, [7, 30, 7, 1]) == [
            dt.date(2026, 10, 1),
            dt.date(2026, 10, 24),
            dt.date(2026, 10, 30),
        ]

    def test_bounds_are_the_twins_bounds(self) -> None:
        due = dt.date(2026, 10, 31)
        with pytest.raises(ValueError, match="1 to 12"):
            calendar.reminder_schedule(due, [])
        with pytest.raises(ValueError, match="1 to 12"):
            calendar.reminder_schedule(due, list(range(13)))
        with pytest.raises(ValueError, match=r"\[0, 365\]"):
            calendar.reminder_schedule(due, [400])


class TestUrgency:
    def test_interrupt_is_reserved_for_waiver_kinds_at_final_approach(self) -> None:
        assert notify.urgency_for("tax_payment_due", 1) == "interrupt_now"
        assert notify.urgency_for("tax_payment_due", 7) == "next_session"
        # A lease expiration never interrupts — nothing waives at midnight.
        assert notify.urgency_for("lease_expiration", 1) == "next_session"


class TestDelivery:
    def test_unconfigured_channel_still_writes_the_ledger(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        # October 24 crosses the 30- and 14-day steps (Oct 1 and Oct 17)
        # and the 7-day step (Oct 24) — three messages, once each, logged.
        result = client.post("/notifications/deliver?as_of=2026-10-24").json()
        assert result["logged"] == 3
        assert result["delivered"] == 0 and result["failed"] == 0
        again = client.post("/notifications/deliver?as_of=2026-10-24").json()
        assert again["logged"] == 0  # exactly one message per step, forever
        rows = client.get("/notifications").json()
        mine = [r for r in rows if r["deadline_id"] == world["deadline"]]
        assert sorted(r["lead_days"] for r in mine) == [7, 14, 30]
        assert {r["channel"] for r in mine} == {"log"}
        assert {r["status"] for r in mine} == {"logged"}

    def test_the_final_step_interrupts_and_speaks_in_the_covenant_voice(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        result = client.post("/notifications/deliver?as_of=2026-10-30").json()
        assert result["interrupts"] == 1
        row = conn.execute(
            """
            SELECT urgency::text, subject, body FROM notifications
            WHERE deadline_id = %s AND lead_days = 1
            """,
            (world["deadline"],),
        ).fetchone()
        assert row is not None and row["urgency"] == "interrupt_now"
        assert "TOMORROW" in row["subject"]
        # Verdict, authority, one action — the DecisionCard grammar.
        assert "due 2026-10-31" in row["body"]
        assert "KRS s.91A.070(2)" in row["body"]
        assert "Act now" in row["body"]

    def test_a_configured_seam_sends_and_records_the_recipient(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        sent: list[tuple[str, str, str]] = []

        def sender(to: str, subject: str, body: str) -> None:
            sent.append((to, subject, body))

        result = notify.deliver(conn, dt.date(2026, 10, 24), seam=(sender, "bri@example.com"))
        conn.commit()
        assert result.delivered == 3 and result.failed == 0
        assert {s[0] for s in sent} == {"bri@example.com"}
        rows = conn.execute(
            "SELECT channel, recipient, status::text FROM notifications WHERE deadline_id = %s",
            (world["deadline"],),
        ).fetchall()
        assert all(r["channel"] == "email" and r["recipient"] == "bri@example.com" for r in rows)
        assert {r["status"] for r in rows} == {"sent"}

    def test_a_failed_send_keeps_its_row_and_retries_into_it(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        def broken(to: str, subject: str, body: str) -> None:
            raise ConnectionError("the wire is down")

        first = notify.deliver(conn, dt.date(2026, 10, 1), seam=(broken, "bri@example.com"))
        conn.commit()
        assert first.failed == 1 and first.delivered == 0
        row = conn.execute(
            "SELECT status::text, attempts, last_error FROM notifications WHERE deadline_id = %s",
            (world["deadline"],),
        ).fetchone()
        assert row is not None and row["status"] == "failed"
        assert row["attempts"] == 1 and "wire is down" in row["last_error"]

        delivered: list[str] = []
        second = notify.deliver(
            conn,
            dt.date(2026, 10, 1),
            seam=(lambda to, s, b: delivered.append(s), "bri@example.com"),
        )
        conn.commit()
        assert second.delivered == 1  # the retry, into the same row
        row = conn.execute(
            "SELECT status::text, attempts, last_error FROM notifications WHERE deadline_id = %s",
            (world["deadline"],),
        ).fetchone()
        assert row is not None and row["status"] == "sent"
        assert row["attempts"] == 2 and row["last_error"] is None
        count = conn.execute(
            "SELECT count(*) AS n FROM notifications WHERE deadline_id = %s",
            (world["deadline"],),
        ).fetchone()
        assert count is not None and count["n"] == 1  # the message, not the attempts

    def test_a_retry_with_no_seam_waits_and_a_broken_retry_counts_again(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        def broken(to: str, subject: str, body: str) -> None:
            raise ConnectionError("still down")

        notify.deliver(conn, dt.date(2026, 10, 1), seam=(broken, "bri@example.com"))
        conn.commit()
        # No seam: the failed row waits — nothing invents a channel.
        held = notify.deliver(conn, dt.date(2026, 10, 1), seam=None)
        conn.commit()
        assert held.delivered == 0 and held.failed == 0 and held.logged == 0
        # A second broken attempt counts itself honestly.
        again = notify.deliver(conn, dt.date(2026, 10, 1), seam=(broken, "bri@example.com"))
        conn.commit()
        assert again.failed == 1
        row = conn.execute(
            "SELECT attempts FROM notifications WHERE deadline_id = %s",
            (world["deadline"],),
        ).fetchone()
        assert row is not None and row["attempts"] == 2

    def test_entity_anchored_deadlines_and_bare_leads_render_too(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        # An entity-anchored deadline (no property) with a window open date,
        # delivered ON its due date (lead 0 crosses when as_of == due_on is
        # inside every step) — the TODAY wording and the runway line render.
        deadline_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO deadlines (id, kind, due_on, window_opens_on, entity_id, citation)
            VALUES (%s, 'estimated_tax', '2026-10-24', '2026-10-01', %s, 'IRC s.6654(c)')
            """,
            (deadline_id, world["entity"]),
        )
        conn.commit()
        notify.deliver(conn, dt.date(2026, 10, 23), seam=None)
        conn.commit()
        row = conn.execute(
            "SELECT body, subject FROM notifications WHERE deadline_id = %s AND lead_days = 1",
            (deadline_id,),
        ).fetchone()
        assert row is not None
        assert "N38" in row["body"]  # the entity carries the address
        assert "The window opened 2026-10-01." in row["body"]

    def test_smtp_seam_absent_when_unconfigured(self) -> None:
        assert notify.smtp_sender() is None

    def test_no_deadlines_means_nothing_to_say(
        self, clean: None, client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        result = notify.deliver(conn, dt.date(2030, 1, 1), seam=None)
        assert result.model_dump() == {
            "delivered": 0,
            "logged": 0,
            "failed": 0,
            "interrupts": 0,
        }


class TestSmtpSeam:
    def test_settings_travel_together_or_not_at_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from hestia_api import config
        from hestia_api.config import ConfigurationError

        for key in ("HESTIA_SMTP_HOST", "HESTIA_SMTP_FROM", "HESTIA_NOTIFY_TO"):
            monkeypatch.delenv(key, raising=False)
        assert config.smtp_settings() is None
        monkeypatch.setenv("HESTIA_SMTP_HOST", "mail.example.com")
        with pytest.raises(ConfigurationError, match="travel"):
            config.smtp_settings()
        monkeypatch.setenv("HESTIA_SMTP_FROM", "hestia@example.com")
        monkeypatch.setenv("HESTIA_NOTIFY_TO", "bri@example.com")
        assert config.smtp_settings() == (
            "mail.example.com",
            587,
            "hestia@example.com",
            "bri@example.com",
        )
        monkeypatch.setenv("HESTIA_SMTP_PORT", "not-a-port")
        with pytest.raises(ConfigurationError, match="integer"):
            config.smtp_settings()

    def test_the_configured_seam_sends_through_smtp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HESTIA_SMTP_HOST", "mail.example.com")
        monkeypatch.setenv("HESTIA_SMTP_PORT", "2525")
        monkeypatch.setenv("HESTIA_SMTP_FROM", "hestia@example.com")
        monkeypatch.setenv("HESTIA_NOTIFY_TO", "bri@example.com")
        sent: list[Any] = []

        class FakeSMTP:
            def __init__(self, host: str, port: int, timeout: int) -> None:
                assert (host, port) == ("mail.example.com", 2525)

            def __enter__(self) -> FakeSMTP:
                return self

            def __exit__(self, *args: Any) -> None:
                return None

            def send_message(self, message: Any) -> None:
                sent.append(message)

        import smtplib

        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        seam = notify.smtp_sender()
        assert seam is not None
        send, recipient = seam
        assert recipient == "bri@example.com"
        send(recipient, "subject line", "body text")
        (message,) = sent
        assert message["From"] == "hestia@example.com"
        assert message["To"] == "bri@example.com"
        assert message["Subject"] == "subject line"
