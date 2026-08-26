"""The Weibull Monte Carlo capital forecast.

Every component carries an install-age band and a Weibull hazard; the simulator
draws failure histories and produces expected capital spend per year with
percentile bands. This is what replaces the industry's flat dollars-per-unit
guess with a defensible reserve — and what makes "sell before the roof, not
after" a computed statement.

Deterministic by construction: a seed is required, the generator is PCG64, and
the same inputs always produce the same output.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ComponentSpec:
    """One installed component, as the inference layer describes it."""

    name: str
    #: Credible age band in years at simulation start; equal ends = known age.
    age_low: float
    age_high: float
    #: Weibull shape; > 1 means the hazard rises with age.
    shape: float
    #: Characteristic life in years.
    scale: float
    replacement_cost_cents: int

    def validate(self) -> None:
        if not 0 <= self.age_low <= self.age_high:
            raise ValueError(f"{self.name}: age band must satisfy 0 <= low <= high")
        if self.shape <= 1:
            raise ValueError(
                f"{self.name}: shape must exceed 1 — a falling hazard is not a component"
            )
        if self.scale <= 0:
            raise ValueError(f"{self.name}: scale must be positive")
        if self.replacement_cost_cents < 0:
            raise ValueError(f"{self.name}: replacement cost must not be negative")


@dataclass(frozen=True)
class CapexForecast:
    years: tuple[int, ...]
    expected_cents: tuple[int, ...]
    p10_cents: tuple[int, ...]
    p50_cents: tuple[int, ...]
    p90_cents: tuple[int, ...]
    total_expected_cents: int


def _conditional_weibull(rng: np.random.Generator, shape: float, scale: float, age: float) -> float:
    """Years until failure for a component that has already survived ``age``.

    Inverse-CDF sampling of the conditional distribution: with survival
    S(t) = exp(-(t/scale)^shape), draw u and solve
    S(age + t) / S(age) = u  =>  t = scale * ((age/scale)^shape - ln u)^(1/shape) - age.
    """
    # random() is [0, 1); 1 - random() is (0, 1], so log(u) is always finite
    # and no unreachable re-draw guard is needed.
    u = 1.0 - rng.random()
    aged = (age / scale) ** shape
    return scale * (aged - np.log(u)) ** (1.0 / shape) - age


def simulate(
    components: list[ComponentSpec],
    horizon_years: int,
    trials: int,
    seed: int,
) -> CapexForecast:
    """Expected capital spend per year over the horizon, with bands."""
    if horizon_years < 1 or horizon_years > 50:
        raise ValueError("horizon_years must be in [1, 50]")
    if trials < 1 or trials > 1_000_000:
        raise ValueError("trials must be in [1, 1000000]")
    for component in components:
        component.validate()

    rng = np.random.default_rng(np.random.PCG64(seed))
    spend = np.zeros((trials, horizon_years), dtype=np.int64)

    for trial in range(trials):
        for component in components:
            age = rng.uniform(component.age_low, component.age_high)
            # First failure is conditional on having survived to `age`;
            # after a replacement the clock restarts unconditionally.
            elapsed = _conditional_weibull(rng, component.shape, component.scale, age)
            while elapsed < horizon_years:
                spend[trial, int(elapsed)] += component.replacement_cost_cents
                elapsed += _conditional_weibull(rng, component.shape, component.scale, 0.0)

    expected = spend.mean(axis=0)
    p10, p50, p90 = (np.percentile(spend, q, axis=0) for q in (10, 50, 90))
    return CapexForecast(
        years=tuple(range(1, horizon_years + 1)),
        expected_cents=tuple(round(float(v)) for v in expected),
        p10_cents=tuple(round(float(v)) for v in p10),
        p50_cents=tuple(round(float(v)) for v in p50),
        p90_cents=tuple(round(float(v)) for v in p90),
        total_expected_cents=round(float(expected.sum())),
    )
