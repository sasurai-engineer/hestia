"""US Census Bureau geocoder — free, keyless, authoritative for FIPS.

Live-recorded fixture: fixtures/census-geocode-newport.json (2026-08-25).
The geographies block is where the jurisdiction resolve begins: county FIPS
21037 is Campbell County and the incorporated-place entry is Newport — the
exact keys the seeded jurisdiction hierarchy carries.
"""

from __future__ import annotations

from dataclasses import dataclass

from hestia_ingest.fetch import ProviderRequest

PROVIDER = "census-geocoder"
BASE_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"


class UnmatchedAddressError(Exception):
    """The geocoder returned no candidate for the address."""


@dataclass(frozen=True)
class GeocodedAddress:
    matched_address: str
    longitude: float
    latitude: float
    state_fips: str
    county_fips: str
    county_name: str
    place_fips: str | None
    place_name: str | None
    tract_geoid: str | None


def build_request(one_line_address: str) -> ProviderRequest:
    address = one_line_address.strip()
    if not address:
        raise ValueError("address must not be empty")
    return ProviderRequest(
        provider=PROVIDER,
        url=BASE_URL,
        params={
            "address": address,
            "benchmark": "Public_AR_Current",
            "vintage": "Current_Current",
            "format": "json",
        },
    )


def _first(geographies: dict, layer: str) -> dict | None:
    entries = geographies.get(layer) or []
    return entries[0] if entries else None


def map_response(payload: dict) -> GeocodedAddress:
    matches = (payload.get("result") or {}).get("addressMatches") or []
    if not matches:
        raise UnmatchedAddressError("the geocoder matched no address")
    match = matches[0]
    coordinates = match.get("coordinates") or {}
    geographies = match.get("geographies") or {}
    county = _first(geographies, "Counties")
    state = _first(geographies, "States")
    if county is None or state is None or "x" not in coordinates or "y" not in coordinates:
        raise UnmatchedAddressError("the geocoder match is missing geography or coordinates")
    place = _first(geographies, "Incorporated Places")
    tract = _first(geographies, "Census Tracts")
    return GeocodedAddress(
        matched_address=str(match.get("matchedAddress", "")),
        longitude=float(coordinates["x"]),
        latitude=float(coordinates["y"]),
        state_fips=str(state["GEOID"]),
        county_fips=str(county["GEOID"]),
        county_name=str(county.get("NAME", "")),
        place_fips=str(place["GEOID"]) if place else None,
        place_name=str(place.get("NAME", "")) if place else None,
        tract_geoid=str(tract["GEOID"]) if tract else None,
    )
