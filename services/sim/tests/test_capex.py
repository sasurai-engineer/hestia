"""The Monte Carlo forecast: deterministic, bounded, and honest about shape."""

import pytest
from hestia_sim.capex import CapexForecast, ComponentSpec, simulate
from hypothesis import given, settings
from hypothesis import strategies as st

ROOF = ComponentSpec(
    "roof", age_low=8, age_high=16, shape=3.0, scale=22.0, replacement_cost_cents=14_000_00
)
WATER_HEATER = ComponentSpec("water-heater", 6, 6, 2.5, 10.0, 1_600_00)


class TestValidation:
    def test_rejects_each_inadmissible_spec(self) -> None:
        with pytest.raises(ValueError, match="age band"):
            ComponentSpec("x", 5, 4, 2, 10, 1).validate()
        with pytest.raises(ValueError, match="age band"):
            ComponentSpec("x", -1, 4, 2, 10, 1).validate()
        with pytest.raises(ValueError, match="shape"):
            ComponentSpec("x", 0, 1, 1.0, 10, 1).validate()
        with pytest.raises(ValueError, match="scale"):
            ComponentSpec("x", 0, 1, 2, 0, 1).validate()
        with pytest.raises(ValueError, match="replacement cost"):
            ComponentSpec("x", 0, 1, 2, 10, -1).validate()

    def test_rejects_bad_horizon_and_trials(self) -> None:
        with pytest.raises(ValueError, match="horizon_years"):
            simulate([ROOF], 0, 10, seed=1)
        with pytest.raises(ValueError, match="horizon_years"):
            simulate([ROOF], 51, 10, seed=1)
        with pytest.raises(ValueError, match="trials"):
            simulate([ROOF], 10, 0, seed=1)
        with pytest.raises(ValueError, match="trials"):
            simulate([ROOF], 10, 1_000_001, seed=1)


class TestDeterminism:
    def test_same_seed_same_forecast(self) -> None:
        a = simulate([ROOF, WATER_HEATER], 10, 500, seed=42)
        b = simulate([ROOF, WATER_HEATER], 10, 500, seed=42)
        assert a == b

    def test_different_seed_different_draws(self) -> None:
        a = simulate([ROOF, WATER_HEATER], 10, 500, seed=42)
        b = simulate([ROOF, WATER_HEATER], 10, 500, seed=43)
        assert a != b


class TestShape:
    def test_forecast_shape_and_consistency(self) -> None:
        forecast = simulate([ROOF, WATER_HEATER], 10, 400, seed=7)
        assert isinstance(forecast, CapexForecast)
        assert forecast.years == tuple(range(1, 11))
        for series in (
            forecast.expected_cents,
            forecast.p10_cents,
            forecast.p50_cents,
            forecast.p90_cents,
        ):
            assert len(series) == 10
            assert all(v >= 0 for v in series)
        for p10, p50, p90 in zip(
            forecast.p10_cents, forecast.p50_cents, forecast.p90_cents, strict=True
        ):
            assert p10 <= p50 <= p90

    def test_no_components_means_no_spend(self) -> None:
        forecast = simulate([], 5, 50, seed=1)
        assert forecast.total_expected_cents == 0
        assert set(forecast.expected_cents) == {0}

    def test_an_aged_component_fails_sooner_than_a_new_one(self) -> None:
        old = simulate([ComponentSpec("r", 20, 20, 3, 22, 100_00)], 10, 2000, seed=5)
        new = simulate([ComponentSpec("r", 0, 0, 3, 22, 100_00)], 10, 2000, seed=5)
        assert old.total_expected_cents > new.total_expected_cents

    @settings(max_examples=15, deadline=None)
    @given(st.integers(1, 20), st.integers(10, 200), st.integers(0, 2**31 - 1))
    def test_totals_reconcile_and_never_go_negative(
        self, horizon: int, trials: int, seed: int
    ) -> None:
        forecast = simulate([WATER_HEATER], horizon, trials, seed=seed)
        assert forecast.total_expected_cents >= 0
        assert len(forecast.expected_cents) == horizon
