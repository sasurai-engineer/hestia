"""The dossier orchestrator: an address in, a filled dossier out.

The magic-moment pipeline (plan section 3), run against the database in one
transaction: geocode -> jurisdiction upgrade -> flood hazard -> component
inference -> latent-defect flags -> deadline sweep. Every network payload is
recorded in ingestion_runs verbatim (mapping bugs get fixed by re-mapping
stored payloads); every inferred row carries provenance; a step that cannot
run says so and the rest still do — never a blank state, never a guess
presented as fact.

The fetch callable is injected: production passes the one bounded HTTP shim,
tests pass the live-recorded fixtures. CI never touches the network.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg
from hestia_ingest.fetch import FetchError, FetchResult, ProviderRequest, fetch_json
from hestia_ingest.inference import infer_components, infer_latent_defects
from hestia_ingest.providers import census, fema

from hestia_api import sweep as sweep_module

Conn = psycopg.Connection[dict[str, Any]]
Fetcher = Callable[[ProviderRequest], FetchResult]

live_fetch: Fetcher = fetch_json


@dataclass(frozen=True)
class Step:
    name: str
    status: str  # ok | skipped | failed
    detail: str


class PropertyNotFound(Exception):
    pass


def _record_run(
    conn: Conn,
    *,
    provider: str,
    endpoint: str,
    property_id: str,
    status: str,
    raw: str | None,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO ingestion_runs
          (provider, endpoint, property_id, status, error_detail, raw_response)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (provider, endpoint, property_id, status, error, raw),
    )


def _provenance(
    conn: Conn, *, kind: str, confidence: float, source_label: str, derived_from: str | None
) -> str:
    row = conn.execute(
        """
        INSERT INTO provenance (kind, confidence, source_label, derived_from)
        VALUES (%s, %s, %s, %s) RETURNING id
        """,
        (kind, confidence, source_label, derived_from),
    ).fetchone()
    return str(row["id"])  # type: ignore[index]


def _geocode(
    conn: Conn, fetch: Fetcher, prop: dict[str, Any]
) -> tuple[Step, census.GeocodedAddress | None]:
    address = f"{prop['street_1']}, {prop['city']}, {prop['state']} {prop['postal_code']}"
    request = census.build_request(address)
    try:
        result = fetch(request)
    except FetchError as error:
        _record_run(
            conn,
            provider=request.provider,
            endpoint=request.url,
            property_id=prop["id"],
            status="error",
            raw=None,
            error=error.detail,
        )
        return Step("geocode", "failed", error.detail), None
    try:
        geocoded = census.map_response(result.payload)
    except census.UnmatchedAddressError as error:
        _record_run(
            conn,
            provider=request.provider,
            endpoint=request.url,
            property_id=prop["id"],
            status="error",
            raw=result.raw_text,
            error=str(error),
        )
        return Step("geocode", "failed", str(error)), None
    _record_run(
        conn,
        provider=request.provider,
        endpoint=request.url,
        property_id=prop["id"],
        status="ok",
        raw=result.raw_text,
    )
    return Step("geocode", "ok", geocoded.matched_address), geocoded


def _upgrade_jurisdiction(
    conn: Conn, prop: dict[str, Any], geocoded: census.GeocodedAddress
) -> Step:
    """The FIPS keys the hierarchy carries beat the name-based resolve. The
    municipality wins where the packs know it (by place FIPS, else by name
    within the state — Census appends the place type, 'Newport city', so the
    closed suffix set is stripped for the comparison); the county is the
    fallback; no match keeps what the name-based resolver already chose."""
    place_names = []
    if geocoded.place_name is not None:
        place_names.append(geocoded.place_name)
        for suffix in (" city", " town", " village", " borough", " CDP"):
            if geocoded.place_name.endswith(suffix):
                place_names.append(geocoded.place_name.removesuffix(suffix))
                break
    resolved = conn.execute(
        """
        SELECT id, level, name FROM jurisdictions
        WHERE (level = 'municipality'
               AND state = %(state)s
               AND (fips_code = %(place_fips)s OR name = ANY(%(place_names)s)))
           OR (level = 'county' AND fips_code = %(county_fips)s)
        ORDER BY CASE level WHEN 'municipality' THEN 0 ELSE 1 END
        LIMIT 1
        """,
        {
            "state": prop["state"],
            "place_fips": geocoded.place_fips,
            "place_names": place_names,
            "county_fips": geocoded.county_fips,
        },
    ).fetchone()
    provenance_id = _provenance(
        conn,
        kind="public_record",
        confidence=1.0,
        source_label="US Census Bureau geocoder",
        derived_from=None,
    )
    conn.execute(
        """
        UPDATE properties
        SET latitude = %s, longitude = %s, county = %s,
            jurisdiction_id = COALESCE(%s, jurisdiction_id),
            provenance_id = %s, updated_at = now()
        WHERE id = %s
        """,
        (
            geocoded.latitude,
            geocoded.longitude,
            geocoded.county_name,
            str(resolved["id"]) if resolved else None,
            provenance_id,
            prop["id"],
        ),
    )
    if resolved is None:
        return Step("jurisdiction", "ok", "coordinates recorded; no pack row matched the FIPS keys")
    return Step("jurisdiction", "ok", f"resolved to {resolved['name']} ({resolved['level']})")


def _flood(
    conn: Conn, fetch: Fetcher, prop: dict[str, Any], geocoded: census.GeocodedAddress
) -> Step:
    request = fema.build_request(geocoded.longitude, geocoded.latitude)
    try:
        result = fetch(request)
    except FetchError as error:
        _record_run(
            conn,
            provider=request.provider,
            endpoint=request.url,
            property_id=prop["id"],
            status="error",
            raw=None,
            error=error.detail,
        )
        return Step("flood", "failed", error.detail)
    _record_run(
        conn,
        provider=request.provider,
        endpoint=request.url,
        property_id=prop["id"],
        status="ok",
        raw=result.raw_text,
    )
    fact = fema.map_response(result.payload)
    if fact is None:
        return Step("flood", "ok", "point is outside any mapped flood polygon")
    provenance_id = _provenance(
        conn,
        kind="public_record",
        confidence=1.0,
        source_label="FEMA National Flood Hazard Layer",
        derived_from=None,
    )
    conn.execute(
        """
        INSERT INTO hazard_facts
          (property_id, kind, zone, in_special_flood_hazard_area,
           base_flood_elevation_ft, map_panel, provenance_id)
        VALUES (%s, 'flood', %s, %s, %s, %s, %s)
        ON CONFLICT (property_id, kind) DO UPDATE
        SET zone = EXCLUDED.zone,
            in_special_flood_hazard_area = EXCLUDED.in_special_flood_hazard_area,
            base_flood_elevation_ft = EXCLUDED.base_flood_elevation_ft,
            map_panel = EXCLUDED.map_panel,
            provenance_id = EXCLUDED.provenance_id,
            observed_at = now()
        """,
        (
            prop["id"],
            fact.zone,
            fact.in_special_flood_hazard_area,
            fact.base_flood_elevation_ft,
            fact.dfirm_id,
            provenance_id,
        ),
    )
    sfha = "IN the special flood hazard area" if fact.in_special_flood_hazard_area else "not SFHA"
    return Step("flood", "ok", f"zone {fact.zone}, {sfha}")


def _components(conn: Conn, prop: dict[str, Any], as_of: dt.date) -> Step:
    if prop["year_built"] is None:
        return Step("components", "skipped", "year_built unknown; nothing to infer from")
    inferred = infer_components(prop["year_built"], as_of.year)
    added = 0
    for component in inferred:
        exists = conn.execute(
            """
            SELECT 1 AS x FROM components c
            JOIN component_types ct ON ct.id = c.component_type_id
            WHERE c.property_id = %s AND ct.code = %s AND c.retired_on IS NULL
            """,
            (prop["id"], component.type_code),
        ).fetchone()
        if exists is not None:
            continue  # inference fills gaps; it never duplicates what is known
        provenance_id = _provenance(
            conn,
            kind=component.provenance_kind,
            confidence=component.confidence,
            source_label="Hestia onboarding inference",
            derived_from=component.derived_from,
        )
        conn.execute(
            """
            INSERT INTO components
              (property_id, component_type_id, installed_year_low,
               installed_year_high, provenance_id)
            SELECT %s, id, %s, %s, %s FROM component_types WHERE code = %s
            """,
            (
                prop["id"],
                component.installed_year_low,
                component.installed_year_high,
                provenance_id,
                component.type_code,
            ),
        )
        added += 1
    return Step("components", "ok", f"{added} inferred, {len(inferred) - added} already present")


def _defects(conn: Conn, prop: dict[str, Any], as_of: dt.date) -> Step:
    if prop["year_built"] is None:
        return Step("defects", "skipped", "year_built unknown; era rules need a vintage")
    flags = infer_latent_defects(prop["year_built"], as_of.year)
    added = 0
    for flag in flags:
        exists = conn.execute(
            "SELECT 1 AS x FROM latent_defects WHERE property_id = %s AND kind = %s",
            (prop["id"], flag.kind),
        ).fetchone()
        if exists is not None:
            continue  # the row may have been confirmed or remediated; never reset it
        provenance_id = _provenance(
            conn,
            kind="inferred",
            confidence=0.6,
            source_label="Hestia era-defect register",
            derived_from=flag.derived_from,
        )
        conn.execute(
            """
            INSERT INTO latent_defects
              (property_id, kind, provenance_id, affects_safety, affects_insurance,
               affects_financing, triggers_disclosure, citation)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                prop["id"],
                flag.kind,
                provenance_id,
                flag.affects_safety,
                flag.affects_insurance,
                flag.affects_financing,
                flag.triggers_disclosure,
                flag.citation,
            ),
        )
        added += 1
    return Step("defects", "ok", f"{added} flagged, {len(flags) - added} already tracked")


def assemble(conn: Conn, property_id: str, *, fetch: Fetcher, as_of: dt.date) -> dict[str, Any]:
    prop = conn.execute(
        """
        SELECT id::text, street_1, city, state, postal_code, year_built
        FROM properties WHERE id = %s
        """,
        (property_id,),
    ).fetchone()
    if prop is None:
        raise PropertyNotFound(property_id)

    steps: list[Step] = []
    geocode_step, geocoded = _geocode(conn, fetch, prop)
    steps.append(geocode_step)
    if geocoded is None:
        steps.append(Step("jurisdiction", "skipped", "no geocode to resolve from"))
        steps.append(Step("flood", "skipped", "no coordinates to probe"))
    else:
        steps.append(_upgrade_jurisdiction(conn, prop, geocoded))
        steps.append(_flood(conn, fetch, prop, geocoded))
    steps.append(_components(conn, prop, as_of))
    steps.append(_defects(conn, prop, as_of))

    sweep_result = sweep_module.run_sweep(conn, as_of)
    steps.append(
        Step(
            "sweep",
            "ok",
            f"{sweep_result.total} deadlines written, {len(sweep_result.gaps)} coverage gaps",
        )
    )
    return {
        "property_id": prop["id"],
        "as_of": str(as_of),
        "steps": [vars(step) for step in steps],
        "sweep": {
            "inserted": sweep_result.inserted,
            "gaps": [vars(gap) for gap in sweep_result.gaps],
        },
    }
