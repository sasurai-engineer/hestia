"""The sweep scheduler — the stack bills the month with no human (issue #39).

Every sweep is an idempotent function behind an audited POST endpoint; this
module makes them RUN unattended while staying honest about the parked
hosting decision (#33): no cron, no systemd, no platform assumption — a
single daemon thread inside the API process, gated by configuration
(``HESTIA_SWEEP_AT``, absent means disabled, so tests and ad-hoc stacks
stay deterministic), serialized across replicas by a Postgres advisory
lock. Idempotency already makes a double-run harmless; the lock makes it
clean.

Each tick runs the rent sweep, the late-fee sweep, and the deadline sweep,
plus the dossier refresh on its configured weekday, and writes one audit
row per sweep under the ``scheduler`` actor with a shared correlation id —
an unattended month leaves the same trail a hand-run one would. One broken
sweep never silences the rest: it is rolled back, audited as failed, and
the tick continues, which is the gap philosophy applied to time.
"""

from __future__ import annotations

import datetime as dt
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg

from hestia_api import db, dossier, rent, sweep
from hestia_api.config import ConfigurationError

Conn = psycopg.Connection[dict[str, Any]]

# 'HESTIA39' as eight ASCII bytes — a stable, greppable advisory-lock key.
SWEEP_LOCK_KEY = 0x4845535449413339


@dataclass(frozen=True)
class Schedule:
    at: dt.time  # UTC, daily
    dossier_weekday: int  # 0 = Monday … 6 = Sunday


def schedule_from_env(env: Callable[[str, str], str]) -> Schedule | None:
    """``HESTIA_SWEEP_AT`` as ``HH:MM`` (UTC) enables the scheduler; absent
    or empty disables it. ``HESTIA_DOSSIER_REFRESH_WEEKDAY`` picks the
    weekly refresh day (0=Monday … 6=Sunday, default Sunday)."""
    raw = env("HESTIA_SWEEP_AT", "").strip()
    if not raw:
        return None
    try:
        at = dt.time.fromisoformat(raw)
    except ValueError as error:
        raise ConfigurationError(
            f"HESTIA_SWEEP_AT must be HH:MM (UTC), received {raw!r}"
        ) from error
    raw_day = env("HESTIA_DOSSIER_REFRESH_WEEKDAY", "6").strip()
    try:
        weekday = int(raw_day)
    except ValueError as error:
        raise ConfigurationError(
            f"HESTIA_DOSSIER_REFRESH_WEEKDAY must be 0..6, received {raw_day!r}"
        ) from error
    if not 0 <= weekday <= 6:
        raise ConfigurationError(
            f"HESTIA_DOSSIER_REFRESH_WEEKDAY must be 0..6, received {raw_day!r}"
        )
    return Schedule(at=at, dossier_weekday=weekday)


def next_run(now: dt.datetime, at: dt.time) -> dt.datetime:
    """Today's configured moment if it is still ahead, else tomorrow's."""
    candidate = dt.datetime.combine(now.date(), at, tzinfo=dt.UTC)
    if candidate <= now:
        candidate += dt.timedelta(days=1)
    return candidate


def _audit_run(conn: Conn, request_id: str, action: str, payload: dict[str, Any]) -> None:
    db.record_audit(
        conn,
        actor="scheduler",
        action=action,
        request_id=request_id,
        table_name=None,
        record_id=None,
        after_value=payload,
    )


def tick(
    conn: Conn,
    *,
    now: dt.datetime,
    dossier_weekday: int,
    fetch: dossier.Fetcher,
) -> dict[str, Any]:
    """One scheduled pass. The advisory lock is session-scoped to this
    connection: a second runner skips honestly instead of racing, and the
    lock dies with the connection if a runner does."""
    got = conn.execute("SELECT pg_try_advisory_lock(%s) AS got", (SWEEP_LOCK_KEY,)).fetchone()
    if got is None or not got["got"]:
        return {"skipped": "another runner holds the sweep lock"}
    try:
        request_id = f"sweep-{uuid.uuid4()}"
        as_of = now.date()
        results: dict[str, Any] = {"request_id": request_id}
        sweeps: list[tuple[str, Callable[[], dict[str, Any]]]] = [
            ("rent.sweep", lambda: rent.sweep_rent_charges(conn, as_of).model_dump()),
            ("latefee.sweep", lambda: rent.sweep_late_fees(conn, as_of).model_dump()),
            (
                "sweep.deadlines",
                lambda: (lambda r: {"inserted": r.inserted, "gaps": len(r.gaps)})(
                    sweep.run_sweep(conn, as_of)
                ),
            ),
        ]
        for action, run in sweeps:
            try:
                outcome = run()
                _audit_run(conn, request_id, action, outcome)
                conn.commit()
                results[action] = "ok"
            except Exception as error:  # one broken sweep never silences the rest
                conn.rollback()
                _audit_run(conn, request_id, f"{action}.failed", {"error": str(error)})
                conn.commit()
                results[action] = f"failed: {error}"
        if now.weekday() == dossier_weekday:
            refreshed = 0
            for row in conn.execute(
                "SELECT id::text FROM properties WHERE disposed_on IS NULL"
            ).fetchall():
                try:
                    dossier.assemble(conn, row["id"], fetch=fetch, as_of=as_of)
                    conn.commit()
                    refreshed += 1
                except Exception as error:  # a dead network must not unbill the month
                    conn.rollback()
                    _audit_run(
                        conn,
                        request_id,
                        "dossier.refresh.failed",
                        {"property_id": row["id"], "error": str(error)},
                    )
                    conn.commit()
            _audit_run(conn, request_id, "dossier.refresh", {"refreshed": refreshed})
            conn.commit()
            results["dossier.refresh"] = refreshed
        return results
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (SWEEP_LOCK_KEY,))
        conn.commit()


def run_loop(
    stop: threading.Event,
    schedule: Schedule,
    connect: Callable[[], AbstractContextManager[Conn]],
    fetch: dossier.Fetcher,
    *,
    waiter: Callable[[float], bool] | None = None,
    clock: Callable[[], dt.datetime] | None = None,
) -> None:
    """Sleep until the next configured moment, tick, repeat — until stopped.
    ``waiter`` and ``clock`` are injectable so the loop itself is testable;
    in production they are the stop event's wait and the UTC clock."""
    wait = waiter if waiter is not None else stop.wait
    read_clock = clock if clock is not None else lambda: dt.datetime.now(dt.UTC)
    while not stop.is_set():
        now = read_clock()
        target = next_run(now, schedule.at)
        if wait(max((target - now).total_seconds(), 0.0)):
            break
        with connect() as conn:
            tick(
                conn,
                now=read_clock(),
                dossier_weekday=schedule.dossier_weekday,
                fetch=fetch,
            )


def connection_factory(url: str) -> Callable[[], AbstractContextManager[Conn]]:
    """A fresh connection per tick: the advisory lock is session-scoped, and
    a long-lived idle connection would hold nothing but risk."""

    @contextmanager
    def open_conn() -> Iterator[Conn]:
        yield from db.connection_for(url)

    return open_conn


__all__ = [
    "SWEEP_LOCK_KEY",
    "Schedule",
    "connection_factory",
    "next_run",
    "run_loop",
    "schedule_from_env",
    "tick",
]
