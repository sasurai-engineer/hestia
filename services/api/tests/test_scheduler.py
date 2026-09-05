"""The sweep scheduler (issue #39): the stack bills the month with no human,
every run leaves its audit trail, and one broken sweep never silences the
rest."""

from __future__ import annotations

import datetime as dt
import threading
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from hestia_api import rent, scheduler
from hestia_api.config import ConfigurationError

UTC = dt.UTC


@pytest.fixture
def world(clean: None, client: TestClient) -> dict[str, str]:
    entity_id = client.post("/entities", json={"name": "S39", "kind": "llc"}).json()["id"]
    property_id = client.post(
        "/properties",
        json={
            "entity_id": entity_id,
            "label": "sched",
            "street_1": "1 Tick St",
            "city": "Newport",
            "state": "KY",
            "postal_code": "41071",
            "kind": "single_family",
        },
    ).json()["id"]
    unit_id = client.post("/units", json={"property_id": property_id, "label": "A"}).json()["id"]
    lease_id = client.post(
        "/leases",
        json={"unit_id": unit_id, "starts_on": "2026-04-01", "rent": "1450.00"},
    ).json()["id"]
    return {"entity": entity_id, "property": property_id, "lease": lease_id}


def env_of(**values: str):
    def env(key: str, default: str = "") -> str:
        return values.get(key, default)

    return env


class TestSchedule:
    def test_absent_or_empty_means_disabled(self) -> None:
        assert scheduler.schedule_from_env(env_of()) is None
        assert scheduler.schedule_from_env(env_of(HESTIA_SWEEP_AT="  ")) is None

    def test_a_time_enables_and_the_weekday_defaults_to_sunday(self) -> None:
        schedule = scheduler.schedule_from_env(env_of(HESTIA_SWEEP_AT="06:00"))
        assert schedule == scheduler.Schedule(at=dt.time(6, 0), dossier_weekday=6)
        monday = scheduler.schedule_from_env(
            env_of(HESTIA_SWEEP_AT="23:30", HESTIA_DOSSIER_REFRESH_WEEKDAY="0")
        )
        assert monday is not None and monday.dossier_weekday == 0

    def test_junk_is_refused_loudly(self) -> None:
        with pytest.raises(ConfigurationError, match="HH:MM"):
            scheduler.schedule_from_env(env_of(HESTIA_SWEEP_AT="six am"))
        with pytest.raises(ConfigurationError, match=r"0\.\.6"):
            scheduler.schedule_from_env(
                env_of(HESTIA_SWEEP_AT="06:00", HESTIA_DOSSIER_REFRESH_WEEKDAY="mon")
            )
        with pytest.raises(ConfigurationError, match=r"0\.\.6"):
            scheduler.schedule_from_env(
                env_of(HESTIA_SWEEP_AT="06:00", HESTIA_DOSSIER_REFRESH_WEEKDAY="7")
            )

    def test_next_run_is_today_ahead_and_tomorrow_behind(self) -> None:
        at = dt.time(6, 0)
        before = dt.datetime(2026, 9, 5, 5, 59, tzinfo=UTC)
        after = dt.datetime(2026, 9, 5, 6, 0, tzinfo=UTC)
        assert scheduler.next_run(before, at) == dt.datetime(2026, 9, 5, 6, 0, tzinfo=UTC)
        # The moment itself has passed the instant it arrives: tomorrow.
        assert scheduler.next_run(after, at) == dt.datetime(2026, 9, 6, 6, 0, tzinfo=UTC)


def _refusing_fetch(request: Any) -> Any:
    raise AssertionError("no network call belongs in this test")


class TestTick:
    def test_a_tick_bills_the_month_and_leaves_the_trail(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        # A Tuesday, so the weekly dossier refresh (Sunday) stays out of the
        # way and no network is touched.
        now = dt.datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
        result = scheduler.tick(conn, now=now, dossier_weekday=6, fetch=_refusing_fetch)
        assert result["rent.sweep"] == "ok"
        assert result["latefee.sweep"] == "ok"
        assert result["sweep.deadlines"] == "ok"
        assert "dossier.refresh" not in result
        charges = conn.execute(
            "SELECT count(*) AS n FROM rent_charges WHERE lease_id = %s",
            (world["lease"],),
        ).fetchone()
        assert charges is not None and charges["n"] == 1
        trail = conn.execute(
            """
            SELECT action FROM audit_log
            WHERE actor = 'scheduler' AND request_id = %s ORDER BY id
            """,
            (result["request_id"],),
        ).fetchall()
        assert [t["action"] for t in trail] == [
            "rent.sweep",
            "latefee.sweep",
            "sweep.deadlines",
        ]

    def test_a_broken_sweep_is_audited_and_the_rest_still_run(
        self,
        world: dict[str, str],
        client: TestClient,
        conn: psycopg.Connection[Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def explode(*_: Any, **__: Any) -> Any:
            raise RuntimeError("late-fee resolution fell over")

        monkeypatch.setattr(rent, "sweep_late_fees", explode)
        now = dt.datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
        result = scheduler.tick(conn, now=now, dossier_weekday=6, fetch=_refusing_fetch)
        assert result["rent.sweep"] == "ok"
        assert result["latefee.sweep"].startswith("failed:")
        assert result["sweep.deadlines"] == "ok"
        failed = conn.execute(
            """
            SELECT after_value FROM audit_log
            WHERE actor = 'scheduler' AND action = 'latefee.sweep.failed'
              AND request_id = %s
            """,
            (result["request_id"],),
        ).fetchone()
        assert failed is not None and "fell over" in str(failed["after_value"])

    def test_the_dossier_refresh_runs_on_its_weekday_and_degrades_per_property(
        self, world: dict[str, str], client: TestClient, conn: psycopg.Connection[Any]
    ) -> None:
        # 2026-09-06 is a Sunday. The refusing fetch makes every property's
        # refresh fail — each failure is audited, the tick survives, and the
        # summary row still lands.
        now = dt.datetime(2026, 9, 6, 6, 0, tzinfo=UTC)
        result = scheduler.tick(conn, now=now, dossier_weekday=6, fetch=_refusing_fetch)
        assert result["dossier.refresh"] == 0
        rows = conn.execute(
            """
            SELECT action FROM audit_log
            WHERE actor = 'scheduler' AND request_id = %s
              AND action LIKE 'dossier.refresh%%'
            """,
            (result["request_id"],),
        ).fetchall()
        actions = [r["action"] for r in rows]
        assert "dossier.refresh" in actions
        assert "dossier.refresh.failed" in actions

    def test_a_second_runner_skips_instead_of_racing(
        self,
        world: dict[str, str],
        client: TestClient,
        conn: psycopg.Connection[Any],
        database_url: str,
    ) -> None:
        with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as rival:
            held = rival.execute(
                "SELECT pg_try_advisory_lock(%s) AS got", (scheduler.SWEEP_LOCK_KEY,)
            ).fetchone()
            assert held is not None and held["got"]
            result = scheduler.tick(
                conn,
                now=dt.datetime(2026, 9, 1, 6, 0, tzinfo=UTC),
                dossier_weekday=6,
                fetch=_refusing_fetch,
            )
            assert result == {"skipped": "another runner holds the sweep lock"}


class TestLoop:
    def test_the_loop_ticks_once_then_stops_on_the_waiter(self) -> None:
        stop = threading.Event()
        waits: list[float] = []
        answers = iter([False, True])

        def waiter(timeout: float) -> bool:
            waits.append(timeout)
            return next(answers)

        ticks: list[dt.datetime] = []

        class FakeConn:
            def __enter__(self) -> FakeConn:
                return self

            def __exit__(self, *args: Any) -> None:
                return None

        real_tick = scheduler.tick
        try:

            def fake_tick(conn: Any, *, now: dt.datetime, **_: Any) -> dict[str, Any]:
                ticks.append(now)
                return {}

            scheduler.tick = fake_tick  # type: ignore[assignment]
            scheduler.run_loop(
                stop,
                scheduler.Schedule(at=dt.time(6, 0), dossier_weekday=6),
                lambda: FakeConn(),  # type: ignore[arg-type,return-value]
                _refusing_fetch,
                waiter=waiter,
                clock=lambda: dt.datetime(2026, 9, 5, 5, 0, tzinfo=UTC),
            )
        finally:
            scheduler.tick = real_tick  # type: ignore[assignment]
        assert len(ticks) == 1
        # The first wait targeted 06:00 from 05:00 — an hour.
        assert waits[0] == pytest.approx(3600.0)

    def test_the_production_clock_reads_utc(self) -> None:
        assert scheduler._utc_now().tzinfo == dt.UTC

    def test_a_pre_set_stop_never_ticks(self) -> None:
        stop = threading.Event()
        stop.set()
        scheduler.run_loop(
            stop,
            scheduler.Schedule(at=dt.time(6, 0), dossier_weekday=6),
            lambda: (_ for _ in ()).throw(AssertionError("must not connect")),  # type: ignore[arg-type,return-value]
            _refusing_fetch,
        )

    def test_the_connection_factory_opens_real_sessions(self, database_url: str) -> None:
        factory = scheduler.connection_factory(database_url)
        with factory() as conn:
            row = conn.execute("SELECT 1 AS one").fetchone()
            assert row is not None and row["one"] == 1


class TestLifespan:
    def test_the_scheduler_thread_starts_and_stops_with_the_app(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Enabled via env: the lifespan starts the thread (it will sleep
        # toward the next 23:59) and joins it cleanly on shutdown.
        from hestia_api import app as app_module

        monkeypatch.setenv("HESTIA_SWEEP_AT", "23:59")
        with TestClient(app_module.app) as running:
            names = [t.name for t in threading.enumerate()]
            assert "hestia-sweep-scheduler" in names
            assert running.get("/deadlines").status_code == 200
        assert "hestia-sweep-scheduler" not in [t.name for t in threading.enumerate()]
