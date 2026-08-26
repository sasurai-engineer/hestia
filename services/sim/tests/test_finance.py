"""The reference implementations, tested in their own right.

These are the other half of the differential contract: if this file weakens,
the fixtures stop being independent evidence.
"""

import json
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path

import pytest
from hestia_sim import finance
from hypothesis import given
from hypothesis import strategies as st

FIXTURES = json.loads(
    (
        Path(__file__).resolve().parents[3] / "packages/engines/fixtures/engine-fixtures.json"
    ).read_text()
)


def cents(text: str) -> int:
    sign = -1 if text.startswith("-") else 1
    whole, frac = [*text.lstrip("-").split("."), "00"][:2]
    return sign * (int(whole) * 100 + int(frac.ljust(2, "0")))


class TestDivRound:
    @given(st.integers(-(10**12), 10**12), st.integers(1, 10**6))
    def test_half_even_matches_the_decimal_oracle(self, num: int, den: int) -> None:
        ours = finance.div_round(num, den, finance.HALF_EVEN)
        oracle = int((Decimal(num) / Decimal(den)).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))
        assert ours == oracle

    @given(st.integers(-(10**12), 10**12), st.integers(1, 10**6))
    def test_half_up_matches_the_decimal_oracle(self, num: int, den: int) -> None:
        ours = finance.div_round(num, den, finance.HALF_UP)
        oracle = int((Decimal(num) / Decimal(den)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        assert ours == oracle

    @given(st.integers(-(10**9), 10**9), st.integers(1, 10**6))
    def test_negative_denominator_normalises(self, num: int, den: int) -> None:
        assert finance.div_round(num, -den, finance.HALF_EVEN) == finance.div_round(
            -num, den, finance.HALF_EVEN
        )

    def test_rejects_zero_and_unknown_modes(self) -> None:
        with pytest.raises(ZeroDivisionError):
            finance.div_round(1, 0, finance.HALF_EVEN)
        with pytest.raises(ValueError):
            finance.div_round(1, 2, "CEILING")


class TestAmortization:
    def test_reproduces_every_fixture(self) -> None:
        for fx in FIXTURES["amortization"]:
            result = finance.amortization(
                cents(fx["principal"]), fx["annualRate"], fx["termMonths"]
            )
            assert result["payment"] == cents(fx["payment"])
            assert result["total_interest"] == cents(fx["totalInterest"])
            assert result["rows"][0]["interest"] == cents(fx["month1Interest"])
            assert result["rows"][-1]["payment"] == cents(fx["finalPayment"])
            assert result["rows"][11]["balance"] == cents(fx["balanceAfter12"])

    @given(
        st.integers(1_00, 10_000_000_00),
        st.integers(0, 1500),
        st.integers(1, 120),
    )
    def test_retires_the_principal_exactly(self, principal: int, bps: int, term: int) -> None:
        rate = f"0.{bps:04d}"
        result = finance.amortization(principal, rate, term)
        assert sum(r["principal"] for r in result["rows"]) == principal
        assert result["rows"][-1]["balance"] == 0

    def test_rejects_degenerate_notes(self) -> None:
        with pytest.raises(ValueError):
            finance.amortization(0, "0.05", 12)
        with pytest.raises(ValueError):
            finance.amortization(100, "0.05", 0)


class TestDepreciation:
    def test_reproduces_every_fixture(self) -> None:
        for fx in FIXTURES["depreciation"]:
            bonus = (
                Fraction(fx["bonusPercent"])
                if "/" in fx["bonusPercent"]
                else Fraction(Decimal(fx["bonusPercent"]))
            )
            result = finance.depreciate(
                cents(fx["basis"]),
                fx["method"],
                fx["lifeYears"],
                fx["convention"],
                bonus,
                cents(fx["section179"]),
                fx["placedInServiceMonth"],
                fx["quarter"],
            )
            assert result["bonus"] == cents(fx["bonus"])
            assert result["schedule"] == [cents(x) for x in fx["schedule"]]

    def test_percentages_sum_to_exactly_one(self) -> None:
        cases = [
            ("27.5", "macrs_sl", "mid_month", 5, None),
            ("39", "macrs_sl", "mid_month", 12, None),
            ("5", "macrs_200db", "half_year", None, None),
            ("7", "macrs_200db", "half_year", None, None),
            ("15", "macrs_150db", "half_year", None, None),
            ("5", "macrs_200db", "mid_quarter", None, 1),
            ("5", "macrs_200db", "mid_quarter", None, 4),
        ]
        for life, method, convention, month, quarter in cases:
            pcts = finance.macrs_percents(life, method, convention, month, quarter)
            assert sum(pcts, Fraction(0)) == 1

    @given(st.integers(1, 10_000_000_00), st.integers(1, 12), st.integers(0, 100))
    def test_total_is_always_the_basis(self, basis: int, month: int, bonus_pct: int) -> None:
        result = finance.depreciate(
            basis, "macrs_sl", "27.5", "mid_month", Fraction(bonus_pct, 100), 0, month, None
        )
        assert result["total"] == basis

    def test_rejects_bad_elections_and_conventions(self) -> None:
        with pytest.raises(ValueError):
            finance.depreciate(0, "macrs_sl", "27.5", "mid_month", Fraction(0), 0, 5, None)
        with pytest.raises(ValueError):
            finance.depreciate(100, "macrs_sl", "27.5", "mid_month", Fraction(2), 0, 5, None)
        with pytest.raises(ValueError):
            finance.first_year_fraction("mid_month", None, None)
        with pytest.raises(ValueError):
            finance.first_year_fraction("mid_quarter", None, 5)
        with pytest.raises(ValueError):
            finance.first_year_fraction("annual", None, None)

    def test_section_179_limit_under_each_state_profile(self) -> None:
        for fx in FIXTURES["section179Limits"]:
            assert finance.section179_limit(
                cents(fx["totalPlacedInService"]), cents(fx["cap"]), cents(fx["phaseoutStart"])
            ) == cents(fx["limit"])
        with pytest.raises(ValueError):
            finance.section179_limit(-1, 25_000_00, 200_000_00)

    def test_state_addback_schedule_matches_fixtures(self) -> None:
        for fx in FIXTURES["conformityAddback"]:
            result = finance.state_addback_schedule(
                cents(fx["accelerated"]),
                fx["numerator"],
                fx["denominator"],
                fx["recoveryYears"],
            )
            assert result["addback"] == cents(fx["addback"]), fx["label"]
            assert result["recovery"] == [cents(c) for c in fx["recovery"]], fx["label"]
            assert sum(result["recovery"]) == result["addback"], fx["label"]

    def test_state_addback_schedule_bounds(self) -> None:
        with pytest.raises(ValueError, match="negative"):
            finance.state_addback_schedule(-1, 2, 3, 6)
        with pytest.raises(ValueError, match="numerator"):
            finance.state_addback_schedule(100, 4, 3, 6)
        with pytest.raises(ValueError, match="numerator"):
            finance.state_addback_schedule(100, 0, 3, 6)
        with pytest.raises(ValueError, match="recovery_years"):
            finance.state_addback_schedule(100, 2, 3, 0)

    def test_ky_wrapper_pinned_to_the_ky_fixture_rows(self) -> None:
        ky_rows = [fx for fx in FIXTURES["section179Limits"] if fx["state"] == "KY"]
        assert ky_rows
        for fx in ky_rows:
            assert cents(fx["cap"]) == finance.KY_2001_S179_CAP_CENTS
            assert cents(fx["phaseoutStart"]) == finance.KY_2001_S179_PHASEOUT_START_CENTS
            assert finance.ky_section179_limit(cents(fx["totalPlacedInService"])) == cents(
                fx["limit"]
            )


class TestCashflowRentInsuranceDisposal:
    def test_npv_matches_fixtures(self) -> None:
        flows = [cents(f) for f in FIXTURES["cashflow"]["flows"]]
        assert finance.npv_cents("0.04", flows) == cents(FIXTURES["cashflow"]["npvAt4pct"])
        assert finance.npv_cents("0.05", flows) == cents(FIXTURES["cashflow"]["npvAt5pct"])
        assert finance.npv_cents("0.06", flows) == cents(FIXTURES["cashflow"]["npvAt6pct"])

    def test_irr_solves_to_the_documented_tolerance(self) -> None:
        flows = [cents(f) for f in FIXTURES["cashflow"]["flows"]]
        solved = finance.irr(flows)
        assert abs(solved - Decimal(FIXTURES["cashflow"]["irrNear"])) <= Decimal(
            FIXTURES["cashflow"]["irrTolerance"]
        )
        assert finance.npv_cents(str(solved), flows) == 0

    def test_irr_edges_and_errors(self) -> None:
        assert finance.irr([-100_00, 1]) == Decimal("-0.9999")
        assert finance.irr([1_00, -11_00]) == Decimal("10")
        with pytest.raises(ValueError):
            finance.irr([-1, 100_00])
        with pytest.raises(ValueError):
            finance.irr([1, 2])
        # A one-iteration budget lands on the midpoint of the surviving half.
        flows = [cents(f) for f in FIXTURES["cashflow"]["flows"]]
        assert finance.irr(flows, iterations=1) == Decimal("1.750075")

    def test_rent_fixtures(self) -> None:
        for fx in FIXTURES["rent"]:
            result = finance.renewal_ev(
                cents(fx["currentRent"]),
                cents(fx["turnCost"]),
                fx["vacancyDays"],
                cents(fx["increase"]),
                Fraction(Decimal(fx["pStay"])),
            )
            assert result["expected_gain"] == cents(fx["expectedGain"])
            assert result["expected_turn_loss"] == cents(fx["expectedTurnLoss"])
            assert result["expected_value"] == cents(fx["expectedValue"])

    def test_coinsurance_fixtures(self) -> None:
        for fx in FIXTURES["coinsurance"]:
            result = finance.coinsurance(
                cents(fx["loss"]),
                cents(fx["carriedLimit"]),
                cents(fx["replacementCost"]),
                Fraction(Decimal(fx["coinsurancePercent"])),
                cents(fx["deductible"]),
            )
            assert result["recovery"] == cents(fx["recovery"])
            assert result["retained"] == cents(fx["retained"])

    def test_disposal_fixtures_and_loss_path(self) -> None:
        for fx in FIXTURES["disposal"]:
            result = finance.disposal(
                cents(fx["salePrice"]),
                cents(fx["sellingCosts"]),
                cents(fx["originalBasis"]),
                cents(fx["depreciationTaken"]),
                fx["kind"],
            )
            assert result["gain"] == cents(fx["gain"])
            assert result["loss"] == cents(fx["loss"])
            assert result["ordinary_1245"] == cents(fx["ordinaryRecapture"])
            assert result["unrecaptured_1250"] == cents(fx["unrecaptured1250"])
            assert result["capital_gain"] == cents(fx["capitalGain"])
