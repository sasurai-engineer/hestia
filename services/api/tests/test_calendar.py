"""The Python calendar twin, pinned to the same anchors as the TS engine."""

import datetime as dt

import pytest
from hestia_api import calendar


def test_the_verified_2026_window() -> None:
    window = calendar.ky_open_inspection_window(2026)
    assert window.opens_on == dt.date(2026, 5, 4)
    assert window.closes_on == dt.date(2026, 5, 18)
    assert window.citation == "KRS 133.045"


def test_the_2027_window_the_platform_must_catch() -> None:
    window = calendar.ky_open_inspection_window(2027)
    assert (window.opens_on, window.closes_on) == (dt.date(2027, 5, 3), dt.date(2027, 5, 17))


def test_next_window_rolls_past_a_closed_one() -> None:
    assert calendar.next_ky_inspection_window(dt.date(2026, 8, 25)).opens_on.year == 2027
    assert calendar.next_ky_inspection_window(dt.date(2026, 4, 1)).opens_on.year == 2026
    # The close date itself still counts: the window is not behind us yet.
    assert calendar.next_ky_inspection_window(dt.date(2026, 5, 18)).opens_on.year == 2026


def test_weekend_rolls_match_the_typescript_engine() -> None:
    assert calendar.federal_estimated_tax_due_dates(2025) == [
        dt.date(2025, 4, 15),
        dt.date(2025, 6, 16),  # June 15 2025 is a Sunday
        dt.date(2025, 9, 15),
        dt.date(2026, 1, 15),
    ]
    assert calendar.form_1099_nec_due_date(2026) == dt.date(2027, 2, 1)  # Jan 31 is a Sunday
    assert calendar.form_1099_nec_due_date(2025) == dt.date(2026, 2, 2)  # Jan 31 is a Saturday
    assert calendar.form_1099_nec_due_date(2024) == dt.date(2025, 1, 31)  # a Friday


def test_saturday_rolls_two_days() -> None:
    assert calendar.roll_forward_from_weekend(dt.date(2026, 5, 9)) == dt.date(2026, 5, 11)
    assert calendar.roll_forward_from_weekend(dt.date(2026, 5, 10)) == dt.date(2026, 5, 11)
    assert calendar.roll_forward_from_weekend(dt.date(2026, 5, 11)) == dt.date(2026, 5, 11)


def test_nth_weekday_anchors() -> None:
    assert calendar.nth_weekday_of_month(2026, 5, 0, 1) == dt.date(2026, 5, 4)
    assert calendar.nth_weekday_of_month(2026, 11, 3, 4) == dt.date(2026, 11, 26)
    assert calendar.nth_weekday_of_month(2026, 3, 1, 5) == dt.date(2026, 3, 31)
    assert calendar.nth_weekday_of_month(2026, 1, 3, 1) == dt.date(2026, 1, 1)


def test_nth_weekday_refuses_nonsense() -> None:
    with pytest.raises(ValueError, match="no occurrence 5"):
        calendar.nth_weekday_of_month(2026, 2, 0, 5)
    with pytest.raises(ValueError, match="month"):
        calendar.nth_weekday_of_month(2026, 13, 0, 1)
    with pytest.raises(ValueError, match="weekday"):
        calendar.nth_weekday_of_month(2026, 5, 7, 1)
    with pytest.raises(ValueError, match="nth"):
        calendar.nth_weekday_of_month(2026, 5, 0, 6)


def test_the_registry_resolves_exactly_the_registered_keys() -> None:
    assert "us-ky.open-inspection" in calendar.APPEAL_WINDOWS
    # Tennessee deliberately registers nothing: its deadline is an
    # administrative date a county sets and moves each year, so a builder
    # there could only be confidently wrong.
    assert not [key for key in calendar.APPEAL_WINDOWS if key.startswith("us-tn.")]
    assert "us-zz.not-a-state" not in calendar.APPEAL_WINDOWS
    builder = calendar.APPEAL_WINDOWS["us-ky.open-inspection"]
    window = builder(2026)
    assert window.opens_on == dt.date(2026, 5, 4)
    assert window.closes_on == dt.date(2026, 5, 18)
    assert window.conference_by == dt.date(2026, 5, 18)


def test_next_window_rolls_only_when_the_close_has_passed() -> None:
    builder = calendar.APPEAL_WINDOWS["us-ky.open-inspection"]
    assert calendar.next_window(builder, dt.date(2026, 8, 25)).closes_on == dt.date(2027, 5, 17)
    assert calendar.next_window(builder, dt.date(2026, 5, 18)).closes_on == dt.date(2026, 5, 18)
    assert calendar.next_window(builder, dt.date(2026, 5, 19)).closes_on == dt.date(2027, 5, 17)


def test_the_ohio_bor_window_anchors() -> None:
    builder = calendar.APPEAL_WINDOWS["us-oh.bor-complaint"]
    assert builder(2027) == calendar.WindowDates(
        opens_on=dt.date(2027, 1, 1), closes_on=dt.date(2027, 3, 31), conference_by=None
    )
    # 2029-03-31 is a Saturday; ORC 1.14 extends to Monday April 2.
    assert builder(2029).closes_on == dt.date(2029, 4, 2)
    assert builder(2029).conference_by is None
    with pytest.raises(ValueError):
        builder(2201)


def test_year_bounds() -> None:
    with pytest.raises(ValueError):
        calendar.first_monday_of_may(1899)
    with pytest.raises(ValueError):
        calendar.first_monday_of_may(2201)
    with pytest.raises(ValueError):
        calendar.federal_estimated_tax_due_dates(2200)
    with pytest.raises(ValueError):
        calendar.form_1099_nec_due_date(2200)
    assert calendar.first_monday_of_may(1900) == dt.date(1900, 5, 7)
