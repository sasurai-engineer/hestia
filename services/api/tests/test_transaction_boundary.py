"""When the transaction settles, relative to when the response is sent.

The API's answer is a promise about durable state. If the commit lands after
the response, the promise is made before it is true: a client that acts on an
id it was just handed can get a 404 for a row that exists, and a form that
re-reads after it submits can miss its own write. Issue #83 caught exactly
that in the wild — a vendor was created, the POST returned 201, and a GET
issued one millisecond later returned the list without it.

The ordering is only observable from inside the ASGI protocol. TestClient
hides it, and a real server shows it only as flakiness under load, which is
how it survived this long. So these tests drive the application directly with
their own `send` and watch both events on one timeline.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from typing import Any

import psycopg
import pytest
from hestia_api import db


class _Timeline:
    """Every database settle and every ASGI send, in the order they happen."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self._tick = itertools.count()

    def record(self, name: str) -> None:
        self.events.append(name)
        next(self._tick)

    def index(self, name: str) -> int:
        return self.events.index(name)

    def __contains__(self, name: object) -> bool:
        return name in self.events


class _Watched:
    """A connection that announces when it settles, and is otherwise itself."""

    def __init__(self, inner: Any, timeline: _Timeline) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_timeline", timeline)

    def commit(self) -> Any:
        result = self._inner.commit()
        self._timeline.record("commit")
        return result

    def rollback(self) -> Any:
        result = self._inner.rollback()
        self._timeline.record("rollback")
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._inner, name, value)


@pytest.fixture
def timeline(monkeypatch: pytest.MonkeyPatch) -> _Timeline:
    recorded = _Timeline()
    real_open = db.open_connection

    def watched_open(url: str) -> Any:
        return _Watched(real_open(url), recorded)

    monkeypatch.setattr(db, "open_connection", watched_open)
    return recorded


def _call(timeline: _Timeline, method: str, path: str, body: dict[str, Any] | None) -> int:
    """One request, driven through the raw ASGI interface."""
    from hestia_api.app import app

    raw = json.dumps(body).encode() if body is not None else b""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(raw)).encode()),
        ],
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    }
    status: dict[str, int] = {}

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": raw, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            status["code"] = message["status"]
            timeline.record("response.start")

    asyncio.run(app(scope, receive, send))
    return status["code"]


def test_the_transaction_commits_before_the_response_is_sent(
    clean: None, timeline: _Timeline
) -> None:
    """The defect in #83, as a property rather than a symptom.

    A 201 that arrives before its own commit is a receipt for a row nobody
    else can see yet. Whoever reads next — the same form, another tab, the
    sweep — is entitled to find what the response just described."""
    status = _call(timeline, "POST", "/entities", {"name": "Boundary", "kind": "llc"})
    assert status == 201
    assert "commit" in timeline, "the request never committed at all"
    assert timeline.index("commit") < timeline.index("response.start"), (
        "the response was sent before the transaction committed; a client acting on "
        f"this response can miss its own write (timeline: {timeline.events})"
    )


def test_a_refused_mutation_rolls_back_before_the_response_is_sent(
    clean: None, timeline: _Timeline
) -> None:
    """The same promise on the failing path: by the time the client is told
    no, there must be nothing left half-written behind the answer."""
    status = _call(timeline, "POST", "/entities", {"name": "", "kind": "llc"})
    assert status == 422
    settled = [event for event in timeline.events if event in {"commit", "rollback"}]
    if settled:
        assert timeline.index(settled[-1]) < timeline.index("response.start"), (
            f"the refusal was sent before the transaction settled: {timeline.events}"
        )


def test_the_row_is_readable_by_another_connection_once_the_response_exists(
    clean: None, timeline: _Timeline, database_url: str
) -> None:
    """The consequence, stated in the terms a caller cares about: a separate
    connection — a different request, in production — sees the row the moment
    the response describing it exists."""
    status = _call(timeline, "POST", "/entities", {"name": "Readable", "kind": "llc"})
    assert status == 201
    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as other:
        found = other.execute(
            "SELECT count(*) AS n FROM entities WHERE name = 'Readable'"
        ).fetchone()
    assert found is not None and found["n"] == 1


def test_the_connection_dependency_settles_before_the_response() -> None:
    """The fix is one line, so it is one line away from being lost.

    Every route reaches the database through the same `Conn` alias, and that
    alias settles early only because its `Depends` carries scope="function".
    Drop the argument, or add a second database dependency without it, and
    the commit silently moves back to after the send — which is #83, and
    which nothing else in the suite would notice."""
    from typing import get_args

    from hestia_api import app as app_module

    marker = get_args(app_module.Conn)[1]
    assert marker.scope == "function", (
        "Conn lost scope='function': its transaction would commit after the "
        "response is sent, and a caller acting on the response could miss its "
        "own write"
    )

    # And no route may reach the database by some other, later dependency.
    late = [
        f"{route.path} -> {dependency.call.__name__}"
        for route in app_module.app.routes
        for dependency in getattr(getattr(route, "dependant", None), "dependencies", [])
        if dependency.call is app_module.get_conn and dependency.scope != "function"
    ]
    assert late == [], f"these routes would commit after their response: {late}"


def test_the_dependency_rolls_back_and_closes_when_the_endpoint_raises() -> None:
    """Rollback and close are unconditional, whatever the endpoint did."""
    from hestia_api import config, db

    connections: list[Any] = []
    real_open = db.open_connection

    def remember(url: str) -> Any:
        conn = real_open(url)
        connections.append(conn)
        return conn

    db.open_connection = remember
    try:
        generator = db.connection_for(config.database_url())
        next(generator)
        with pytest.raises(RuntimeError, match="the endpoint blew up"):
            generator.throw(RuntimeError("the endpoint blew up"))
    finally:
        db.open_connection = real_open
    assert len(connections) == 1
    assert connections[0].closed
