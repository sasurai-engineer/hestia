"""FEMA National Flood Hazard Layer — free, keyless, the lender's authority.

Live-recorded fixture: fixtures/fema-nfhl-newport.json (zone X at the Newport
City Building, 2026-08-25). The -9999 sentinel for an absent base flood
elevation was confirmed live; the in-SFHA branch is exercised by a fixture
whose SHAPE was recorded and whose attribute values are altered — see
fixtures/fema-nfhl-sfha-derived.json and its _note.
"""

from __future__ import annotations

from dataclasses import dataclass

from hestia_ingest.fetch import ProviderRequest

PROVIDER = "fema-nfhl"
BASE_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"

#: FEMA's null sentinel for STATIC_BFE, confirmed against the live layer.
BFE_SENTINEL = -9999.0


@dataclass(frozen=True)
class FloodFact:
    zone: str
    zone_subtype: str | None
    in_special_flood_hazard_area: bool
    base_flood_elevation_ft: float | None
    dfirm_id: str | None


def build_request(longitude: float, latitude: float) -> ProviderRequest:
    if not (-180.0 <= longitude <= 180.0 and -90.0 <= latitude <= 90.0):
        raise ValueError(f"coordinates out of range: {longitude}, {latitude}")
    return ProviderRequest(
        provider=PROVIDER,
        url=BASE_URL,
        params={
            "geometry": f"{longitude},{latitude}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE,DFIRM_ID",
            "returnGeometry": "false",
            "f": "json",
        },
    )


def map_response(payload: dict) -> FloodFact | None:
    """None when the point is outside any mapped flood polygon — which is an
    answer (unmapped), distinct from zone X (mapped, minimal hazard)."""
    features = payload.get("features") or []
    if not features:
        return None
    attributes = features[0].get("attributes") or {}
    zone = attributes.get("FLD_ZONE")
    if not zone:
        return None
    bfe = attributes.get("STATIC_BFE")
    elevation = None if bfe is None or float(bfe) == BFE_SENTINEL else float(bfe)
    subtype = attributes.get("ZONE_SUBTY")
    return FloodFact(
        zone=str(zone),
        zone_subtype=str(subtype) if subtype else None,
        in_special_flood_hazard_area=attributes.get("SFHA_TF") == "T",
        base_flood_elevation_ft=elevation,
        dfirm_id=str(attributes["DFIRM_ID"]) if attributes.get("DFIRM_ID") else None,
    )
