"""The correspondent channel (issue #38; VISION P3, §7 Act I).

For most of the year Hestia is a correspondent, not a cockpit — so what it
sends is a primary surface, held to the same law as what it books. Every
message is a DecisionCard in the covenant's voice: the verdict (what and
when), the authority (the deadline row's own citation), and one action —
never a feelings update, never a summary of nothing.

The three standing urgency classes are typed at the schema and assigned
conservatively here: ``interrupt_now`` is RESERVED for a money-or-waiver
date at its final step (refusal 13: the first false interrupt is a
covenant breach of its own kind); everything else waits in the digest as
``next_session``. Corrections to already-delivered dates ride the same
discipline when they come.

Delivery is idempotent by construction: one message per (deadline,
reminder step), a database fact (module 029). The provider is a seam — an
injected ``send`` callable; SMTP when configured, and when it is not, the
message is still written to the ledger under channel ``log``, because the
record of what Hestia would have said is itself a deliverable.
"""

from __future__ import annotations

import datetime as dt
import smtplib
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

import psycopg
from pydantic import BaseModel

from hestia_api import calendar, config

Conn = psycopg.Connection[dict[str, Any]]

# The default runway: a month out, two weeks, one week, the day before.
DEFAULT_LEADS = [30, 14, 7, 1]

# Kinds whose FINAL reminder step may interrupt: missing them waives a
# right or attaches a penalty by operation of law. Everything else waits.
INTERRUPT_KINDS = frozenset(
    {
        "assessment_appeal_window",
        "tax_payment_due",
        "deposit_itemization",
        "adverse_action_notice",
    }
)


def urgency_for(kind: str, lead_days: int) -> str:
    """Conservative by doctrine: interrupt_now only for a waiver-or-penalty
    kind at its final approach (two days or fewer); the digest carries the
    rest. Dates that err early must never cry wolf."""
    if kind in INTERRUPT_KINDS and lead_days <= 2:
        return "interrupt_now"
    return "next_session"


@dataclass(frozen=True)
class Message:
    deadline_id: str
    lead_days: int
    urgency: str
    subject: str
    body: str


class DeliveryOut(BaseModel):
    delivered: int
    logged: int
    failed: int
    interrupts: int


class NotificationOut(BaseModel):
    id: str
    deadline_id: str
    lead_days: int
    urgency: str
    channel: str
    recipient: str | None
    subject: str
    status: str
    attempts: int
    delivered_at: dt.datetime


def _compose(row: dict[str, Any], lead_days: int) -> Message:
    """The covenant's voice: verdict, authority, one action. The citation is
    the deadline row's own — the code carries no state's statutes."""
    kind = row["kind"]
    due = row["due_on"]
    label = row["property_label"] or row["entity_name"] or "the portfolio"
    urgency = urgency_for(kind, lead_days)
    when = "TOMORROW" if lead_days == 1 else f"in {lead_days} days" if lead_days else "TODAY"
    subject = f"[Hestia] {kind.replace('_', ' ')} — {due.isoformat()} ({when})"
    runway = (
        f"The window opened {row['window_opens_on'].isoformat()}. "
        if row["window_opens_on"]
        else ""
    )
    note = f"\n{row['note']}\n" if row["note"] else ""
    action = (
        "Act now: this date waives a right or attaches a penalty by law."
        if urgency == "interrupt_now"
        else "It is prepared and waiting in Hestia; nothing else needs you today."
    )
    body = (
        f"{label}: {kind.replace('_', ' ')} is due {due.isoformat()} ({when}).\n"
        f"{runway}"
        f"Authority: {row['citation']}\n"
        f"{note}"
        f"{action}\n"
    )
    return Message(
        deadline_id=row["id"],
        lead_days=lead_days,
        urgency=urgency,
        subject=subject,
        body=body,
    )


def due_messages(conn: Conn, as_of: dt.date) -> list[Message]:
    """Every (deadline, step) whose reminder date has arrived and whose
    message has not been written — the crossing, not the calendar, is what
    fires, so a stack that slept through a step still sends it once."""
    rows = conn.execute(
        """
        SELECT d.id::text, d.kind::text, d.due_on, d.window_opens_on,
               d.citation, d.note,
               p.label AS property_label, e.name AS entity_name
        FROM deadlines d
        LEFT JOIN properties p ON p.id = d.property_id
        LEFT JOIN entities e ON e.id = d.entity_id
        WHERE d.status = 'upcoming' AND d.due_on >= %(as_of)s
        ORDER BY d.due_on, d.id
        """,
        {"as_of": as_of},
    ).fetchall()
    if not rows:
        return []
    written = {
        (n["deadline_id"], n["lead_days"])
        for n in conn.execute(
            "SELECT deadline_id::text AS deadline_id, lead_days FROM notifications"
        ).fetchall()
    }
    messages: list[Message] = []
    for row in rows:
        for remind_on in calendar.reminder_schedule(row["due_on"], DEFAULT_LEADS):
            lead = (row["due_on"] - remind_on).days
            if remind_on <= as_of and (row["id"], lead) not in written:
                messages.append(_compose(row, lead))
    return messages


Sender = Callable[[str, str, str], None]  # (recipient, subject, body) -> None


def smtp_sender() -> tuple[Sender, str] | None:
    """The live seam: (sender, recipient) when SMTP + recipient are
    configured, else None — and the ledger still records under 'log'."""
    settings = config.smtp_settings()
    if settings is None:
        return None
    host, port, sender_addr, recipient = settings

    def send(to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = sender_addr
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.send_message(message)

    return send, recipient


def deliver(
    conn: Conn,
    as_of: dt.date,
    *,
    seam: tuple[Sender, str] | None,
) -> DeliveryOut:
    """Write-then-send, one row per message: the ledger is the source of
    truth and a send failure keeps its row and retries into it (module
    029's one exception to append-only — the identity protected is the
    message, not the attempt)."""
    delivered = logged = failed = interrupts = 0
    # Retry earlier failures first — same rows, one more attempt.
    for prior in conn.execute(
        """
        SELECT id::text, deadline_id::text AS deadline_id, lead_days, urgency::text,
               recipient, subject, body
        FROM notifications WHERE status = 'failed'
        """
    ).fetchall():
        if seam is None:
            continue
        send, recipient = seam
        try:
            send(recipient, prior["subject"], prior["body"])
            conn.execute(
                """
                UPDATE notifications
                SET status = 'sent', attempts = attempts + 1, last_error = NULL,
                    channel = 'email', recipient = %s, delivered_at = now()
                WHERE id = %s
                """,
                (recipient, prior["id"]),
            )
            delivered += 1
        except Exception as error:
            conn.execute(
                "UPDATE notifications SET attempts = attempts + 1, last_error = %s WHERE id = %s",
                (str(error), prior["id"]),
            )
            failed += 1
    for message in due_messages(conn, as_of):
        if message.urgency == "interrupt_now":
            interrupts += 1
        if seam is None:
            conn.execute(
                """
                INSERT INTO notifications
                  (deadline_id, lead_days, urgency, channel, recipient,
                   subject, body, status)
                VALUES (%s, %s, %s, 'log', NULL, %s, %s, 'logged')
                ON CONFLICT (deadline_id, lead_days) DO NOTHING
                """,
                (
                    message.deadline_id,
                    message.lead_days,
                    message.urgency,
                    message.subject,
                    message.body,
                ),
            )
            logged += 1
            continue
        send, recipient = seam
        try:
            send(recipient, message.subject, message.body)
            status, error = "sent", None
            delivered += 1
        except Exception as caught:
            status, error = "failed", str(caught)
            failed += 1
        conn.execute(
            """
            INSERT INTO notifications
              (deadline_id, lead_days, urgency, channel, recipient,
               subject, body, status, last_error)
            VALUES (%s, %s, %s, 'email', %s, %s, %s, %s, %s)
            ON CONFLICT (deadline_id, lead_days) DO NOTHING
            """,
            (
                message.deadline_id,
                message.lead_days,
                message.urgency,
                recipient,
                message.subject,
                message.body,
                status,
                error,
            ),
        )
    return DeliveryOut(delivered=delivered, logged=logged, failed=failed, interrupts=interrupts)


def recent(conn: Conn, limit: int) -> list[NotificationOut]:
    rows = conn.execute(
        """
        SELECT id::text, deadline_id::text AS deadline_id, lead_days,
               urgency::text, channel, recipient, subject, status::text,
               attempts, delivered_at
        FROM notifications ORDER BY delivered_at DESC, id LIMIT %s
        """,
        (limit,),
    ).fetchall()
    return [NotificationOut(**row) for row in rows]
