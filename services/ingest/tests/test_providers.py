"""Provider mappers against the live-recorded fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hestia_ingest.providers import census, fema

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class TestCensus:
    def test_builds_the_documented_request(self) -> None:
        request = census.build_request("  998 Monmouth St, Newport, KY 41071 ")
        assert request.provider == "census-geocoder"
        assert request.url == census.BASE_URL
        assert request.params["address"] == "998 Monmouth St, Newport, KY 41071"
        assert request.params["benchmark"] == "Public_AR_Current"
        assert request.params["vintage"] == "Current_Current"
        assert request.params["format"] == "json"
        assert "address=998+Monmouth" in request.full_url

    def test_rejects_an_empty_address(self) -> None:
        with pytest.raises(ValueError):
            census.build_request("   ")

    def test_maps_the_recorded_newport_response(self) -> None:
        geocoded = census.map_response(load("census-geocode-newport.json"))
        assert geocoded.matched_address == "998 MONMOUTH ST, NEWPORT, KY, 41071"
        assert geocoded.state_fips == "21"
        # Campbell County — the seeded jurisdiction hierarchy's FIPS key.
        assert geocoded.county_fips == "21037"
        assert "Campbell" in geocoded.county_name
        assert geocoded.place_name is not None and "Newport" in geocoded.place_name
        assert geocoded.tract_geoid == "21037050500"
        assert -85 < geocoded.longitude < -84
        assert 39 < geocoded.latitude < 40

    def test_no_match_is_a_typed_error(self) -> None:
        with pytest.raises(census.UnmatchedAddressError):
            census.map_response({"result": {"addressMatches": []}})
        with pytest.raises(census.UnmatchedAddressError):
            census.map_response({})

    def test_a_match_missing_geography_is_refused_not_guessed(self) -> None:
        payload = load("census-geocode-newport.json")
        match = payload["result"]["addressMatches"][0]
        del match["geographies"]["Counties"]
        with pytest.raises(census.UnmatchedAddressError):
            census.map_response(payload)

    def test_a_match_without_place_still_maps(self) -> None:
        payload = load("census-geocode-newport.json")
        match = payload["result"]["addressMatches"][0]
        match["geographies"].pop("Incorporated Places")
        match["geographies"].pop("Census Tracts")
        geocoded = census.map_response(payload)
        assert geocoded.place_fips is None
        assert geocoded.place_name is None
        assert geocoded.tract_geoid is None


class TestFema:
    def test_builds_the_documented_request(self) -> None:
        request = fema.build_request(-84.4889, 39.0872)
        assert request.provider == "fema-nfhl"
        assert request.params["geometry"] == "-84.4889,39.0872"
        assert request.params["inSR"] == "4326"
        assert request.params["returnGeometry"] == "false"

    def test_rejects_out_of_range_coordinates(self) -> None:
        with pytest.raises(ValueError):
            fema.build_request(-181, 39)
        with pytest.raises(ValueError):
            fema.build_request(-84, 91)

    def test_maps_the_recorded_zone_x_response(self) -> None:
        fact = fema.map_response(load("fema-nfhl-newport.json"))
        assert fact is not None
        assert fact.zone == "X"
        assert fact.in_special_flood_hazard_area is False
        # -9999 is FEMA's live-confirmed null sentinel, never an elevation.
        assert fact.base_flood_elevation_ft is None

    def test_maps_the_sfha_branch(self) -> None:
        fact = fema.map_response(load("fema-nfhl-sfha-derived.json"))
        assert fact is not None
        assert fact.zone == "AE"
        assert fact.zone_subtype == "FLOODWAY"
        assert fact.in_special_flood_hazard_area is True
        assert fact.base_flood_elevation_ft == 512.3
        assert fact.dfirm_id == "21037C"

    def test_unmapped_is_none_not_zone_x(self) -> None:
        assert fema.map_response({"features": []}) is None
        assert fema.map_response({}) is None
        assert fema.map_response({"features": [{"attributes": {"FLD_ZONE": ""}}]}) is None
