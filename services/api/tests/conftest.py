"""API tests run against a REAL PostgreSQL, migrated by the real runner.

Two modes, chosen by environment:
- HESTIA_TEST_DATABASE_URL set (CI): use that server, reset + migrate.
- otherwise: spin a disposable podman/docker postgres:17-alpine, migrate via
  the container's own psql, tear it down afterwards.

No mocks of the database anywhere — the schema's constraints are part of what
these tests exercise.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[3]
MIGRATE = REPO / "scripts" / "migrate.py"
SCHEMA_DIR = REPO / "packages" / "domain" / "schema"
CONTAINER = "hestia-api-test"


def _run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)


def _migrate(psql_cmd: str) -> None:
    result = _run(
        [
            sys.executable,
            str(MIGRATE),
            "--schema-dir",
            str(SCHEMA_DIR),
            "--include-seeds",
            "--psql",
            psql_cmd,
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"migration failed:\n{result.stdout}{result.stderr}")


def _reset(psql_cmd: str) -> None:
    result = _run(
        [
            *psql_cmd.split(),
            "-v",
            "ON_ERROR_STOP=1",
            "-q",
            "-c",
            "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"schema reset failed: {result.stderr}")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def _database_server() -> Iterator[tuple[str, str]]:
    """(url, psql_cmd) for a running PostgreSQL — container or CI service."""
    env_url = os.environ.get("HESTIA_TEST_DATABASE_URL")
    if env_url:
        yield env_url, f"psql {env_url}"
        return

    engine = shutil.which("podman") or shutil.which("docker")
    if engine is None:
        pytest.fail("no HESTIA_TEST_DATABASE_URL and no container engine available")
    port = _free_port()
    _run([engine, "rm", "-f", CONTAINER])
    started = _run(
        [
            engine,
            "run",
            "-d",
            "--name",
            CONTAINER,
            "-e",
            "POSTGRES_PASSWORD=verify",  # config-audit: allow
            "-e",
            "POSTGRES_DB=hestia",
            "-p",
            f"{port}:5432",
            "docker.io/library/postgres:17-alpine",
        ]
    )
    if started.returncode != 0:
        pytest.fail(f"could not start postgres container: {started.stderr}")
    psql_cmd = f"{engine} exec -i {CONTAINER} psql -U postgres -d hestia"
    try:
        for _ in range(60):
            probe = _run([*psql_cmd.split(), "-tAc", "select 1"])
            if probe.returncode == 0:
                break
            time.sleep(1)
        else:
            pytest.fail("postgres container never became ready")
        yield f"postgresql://postgres:verify@127.0.0.1:{port}/hestia", psql_cmd
    finally:
        _run([engine, "rm", "-f", CONTAINER])


@pytest.fixture(scope="module")
def database_url(_database_server: tuple[str, str]) -> str:
    """A FRESH schema per test module, applied by the real migration runner.

    Module-scoped on purpose: the ledger is append-only (UPDATE/DELETE/TRUNCATE
    are refused by trigger), so any test that writes a ledger event pins its
    anchors for as long as the schema lives — a session-scoped database would
    leak every module's world into the next. A reset-and-remigrate costs about
    two seconds and buys order-independence forever.
    """
    url, psql_cmd = _database_server
    _reset(psql_cmd)
    _migrate(psql_cmd)
    return url


@pytest.fixture(autouse=True)
def _point_app_at_database(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HESTIA_DATABASE_URL", database_url)


@pytest.fixture
def conn(database_url: str) -> Iterator[psycopg.Connection[Any]]:
    connection = psycopg.connect(database_url, row_factory=psycopg.rows.dict_row)
    yield connection
    connection.commit()
    connection.close()


@pytest.fixture
def clean(conn: psycopg.Connection[Any]) -> None:
    """Empty the mutable portfolio tables; seeds stay. Two append-only tables
    constrain this: audit_log is asserted by request-id rather than wiped, and
    ledger_events PINS its anchors (RESTRICT refs, no deletes ever) — so any
    unit/lease/property/entity a ledger row references survives the clean, and
    tests that write ledger rows must scope their assertions to their own
    world rather than to a globally empty one."""
    for table in (
        "deadlines",
        "exchanges",
        "debt_instruments",
        "policies",
        "tax_elections",
        "tax_profiles",
        "disclosures",
        # Bank staging is mutable by design; only the LEDGER rows it produced
        # survive (and pin their anchors, handled below).
        "bank_transactions",
        "bank_import_batches",
        "bank_accounts",
    ):
        conn.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed identifiers above
    conn.execute("DELETE FROM categorization_rules WHERE origin = 'user'")
    # A statement document referenced by an accepted ledger row is pinned
    # (ledger_events_document_fk) — like every anchor the ledger touches.
    conn.execute(
        """
        DELETE FROM source_documents s
        WHERE NOT EXISTS (SELECT 1 FROM ledger_events e WHERE e.document_id = s.id)
        """
    )
    conn.execute(
        """
        DELETE FROM leases l
        WHERE NOT EXISTS (SELECT 1 FROM ledger_events e WHERE e.lease_id = l.id)
        """
    )
    conn.execute(
        """
        DELETE FROM units u
        WHERE NOT EXISTS (SELECT 1 FROM ledger_events e WHERE e.unit_id = u.id)
          AND NOT EXISTS (SELECT 1 FROM leases l WHERE l.unit_id = u.id)
        """
    )
    conn.execute(
        """
        DELETE FROM properties p
        WHERE NOT EXISTS (SELECT 1 FROM ledger_events e WHERE e.property_id = p.id)
          AND NOT EXISTS (SELECT 1 FROM units u WHERE u.property_id = p.id)
        """
    )
    conn.execute(
        """
        DELETE FROM entities x
        WHERE NOT EXISTS (SELECT 1 FROM ledger_events e WHERE e.entity_id = x.id)
          AND NOT EXISTS (SELECT 1 FROM properties p WHERE p.entity_id = x.id)
        """
    )
    conn.commit()


@pytest.fixture
def client() -> Iterator[TestClient]:
    from hestia_api.app import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def newport_property(clean: None, client: TestClient) -> str:
    """The canonical test property: the recorded-fixture address, 1962."""
    entity_id = client.post("/entities", json={"name": "D", "kind": "llc"}).json()["id"]
    return client.post(
        "/properties",
        json={
            "entity_id": entity_id,
            "label": "998 Monmouth",
            "street_1": "998 Monmouth St",
            "city": "Newport",
            "state": "KY",
            "postal_code": "41071",
            "kind": "single_family",
            "year_built": 1962,
        },
    ).json()["id"]


@pytest.fixture
def flaky_client() -> Iterator[TestClient]:
    """A client that surfaces server errors as 500s instead of raising."""
    from hestia_api.app import app

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
