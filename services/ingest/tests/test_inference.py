"""The onboarding inference engine — including the cross-file consistency
check that keeps it honest against the seeded catalog."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from hestia_ingest.inference import (
    CATALOG_LIVES,
    PERMIT_KIND_TO_CODE,
    PermitRecord,
    infer_components,
    infer_latent_defects,
)
from hypothesis import given
from hypothesis import strategies as st

SEED = Path(__file__).resolve().parents[3] / "packages/domain/schema/seed/901_component_catalog.sql"


class TestCatalogConsistency:
    def test_every_inference_band_matches_the_seeded_catalog(self) -> None:
        """The inference and the capex simulation must reason from the SAME
        lifetimes. This parses the seed SQL and fails on any divergence."""
        text = SEED.read_text()
        seeded: dict[str, tuple[float, float]] = {}
        pattern = re.compile(r"\('([\w.]+)',\s*'\w+',\s*'[^']*',\s*\n?\s*(\d+),\s*(\d+),")
        for code, low, high in pattern.findall(text):
            seeded[code] = (float(low), float(high))
        assert len(seeded) >= 25, "seed parse failed; the regex no longer matches the file"
        for code, band in CATALOG_LIVES.items():
            assert code in seeded, f"{code} is not in the seeded catalog"
            assert seeded[code] == band, f"{code}: inference {band} != seed {seeded[code]}"

    def test_every_permit_kind_maps_into_the_catalog(self) -> None:
        for code in PERMIT_KIND_TO_CODE.values():
            assert code in CATALOG_LIVES


class TestComponents:
    def test_a_young_building_is_presumed_original(self) -> None:
        rows = infer_components(year_built=2020, observed_year=2026)
        by_code = {r.type_code: r for r in rows}
        roof = by_code["roof.asphalt_shingle.architectural"]
        assert (roof.installed_year_low, roof.installed_year_high) == (2020, 2020)
        assert roof.provenance_kind == "inferred"
        assert roof.confidence == 0.75
        assert "presumed original" in roof.derived_from
        # The water heater band (8-12) is also un-exceeded at age 6.
        assert by_code["water_heater.tank"].installed_year_low == 2020

    def test_an_old_building_gets_an_honest_wide_band(self) -> None:
        rows = infer_components(year_built=1962, observed_year=2026)
        roof = next(r for r in rows if r.type_code == "roof.asphalt_shingle.architectural")
        assert roof.installed_year_low == 2001  # observed - life_high(25)
        assert roof.installed_year_high == 2026
        assert roof.confidence == 0.5
        assert "replaced at least once" in roof.derived_from

    def test_a_permit_trumps_the_vintage_heuristic(self) -> None:
        rows = infer_components(
            1962, 2026, [PermitRecord("roof", 2016), PermitRecord("landscaping", 2019)]
        )
        roof = next(r for r in rows if r.type_code == "roof.asphalt_shingle.architectural")
        assert (roof.installed_year_low, roof.installed_year_high) == (2016, 2016)
        assert roof.provenance_kind == "public_record"
        assert roof.confidence == 0.9
        assert "permit issued 2016" in roof.derived_from

    def test_the_latest_of_several_permits_wins(self) -> None:
        rows = infer_components(
            1962, 2026, [PermitRecord("roof", 1998), PermitRecord("roof", 2016)]
        )
        roof = next(r for r in rows if r.type_code == "roof.asphalt_shingle.architectural")
        assert roof.installed_year_low == 2016

    def test_band_never_precedes_construction(self) -> None:
        rows = infer_components(year_built=2010, observed_year=2026)
        heater = next(r for r in rows if r.type_code == "water_heater.tank")
        # observed - life_high(12) = 2014 > year_built, so the floor is 2014...
        assert heater.installed_year_low == 2014
        recent = infer_components(year_built=2018, observed_year=2026)
        fresh_paint = next(r for r in recent if r.type_code == "exterior.paint")
        # age 8 exceeds paint's minimum 5; floor clamps to construction.
        assert fresh_paint.installed_year_low == 2018

    def test_validation_rejects_impossible_inputs(self) -> None:
        with pytest.raises(ValueError):
            infer_components(1500, 2026)
        with pytest.raises(ValueError):
            infer_components(2020, 2019)
        with pytest.raises(ValueError):
            infer_components(2020, 2300)
        with pytest.raises(ValueError):
            infer_components(1990, 2026, [PermitRecord("roof", 1980)])
        with pytest.raises(ValueError):
            infer_components(1990, 2026, [PermitRecord("roof", 2027)])

    @given(
        st.integers(1900, 2020),
        st.integers(0, 80),
    )
    def test_bands_are_always_ordered_and_inside_history(self, built: int, age: int) -> None:
        observed = built + age
        if observed > 2200:
            observed = 2200
        for row in infer_components(built, observed):
            assert built <= row.installed_year_low <= row.installed_year_high <= observed
            assert 0 < row.confidence <= 1
            assert row.derived_from


class TestLatentDefects:
    def test_a_1962_building_carries_the_expected_register(self) -> None:
        kinds = {f.kind for f in infer_latent_defects(1962, 2026)}
        assert kinds == {
            "lead_paint",
            "asbestos",
            "orangeburg_sewer",
            "cast_iron_drain",
        }

    def test_lead_paint_carries_its_statute_and_disclosure_duty(self) -> None:
        lead = next(f for f in infer_latent_defects(1970, 2026) if f.kind == "lead_paint")
        assert lead.triggers_disclosure is True
        assert lead.citation is not None and "4852d" in lead.citation

    def test_era_boundaries_are_exact(self) -> None:
        assert any(f.kind == "lead_paint" for f in infer_latent_defects(1977, 2026))
        assert not any(f.kind == "lead_paint" for f in infer_latent_defects(1978, 2026))
        assert any(f.kind == "aluminium_branch_wiring" for f in infer_latent_defects(1965, 2026))
        assert any(f.kind == "aluminium_branch_wiring" for f in infer_latent_defects(1973, 2026))
        assert not any(
            f.kind == "aluminium_branch_wiring" for f in infer_latent_defects(1964, 2026)
        )
        assert not any(
            f.kind == "aluminium_branch_wiring" for f in infer_latent_defects(1974, 2026)
        )
        assert any(f.kind == "polybutylene_supply" for f in infer_latent_defects(1995, 2026))
        assert not any(f.kind == "polybutylene_supply" for f in infer_latent_defects(1996, 2026))

    def test_a_new_building_carries_nothing(self) -> None:
        assert infer_latent_defects(2020, 2026) == []

    def test_heuristic_flags_admit_they_are_heuristics(self) -> None:
        for flag in infer_latent_defects(1950, 2026):
            if flag.kind != "lead_paint":
                assert flag.citation is None
            assert "built 1950" in flag.derived_from

    def test_validation_matches_components(self) -> None:
        with pytest.raises(ValueError):
            infer_latent_defects(2020, 2019)
