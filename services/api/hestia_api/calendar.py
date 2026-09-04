"""Calendar arithmetic — the Python twin of the TypeScript deadline engine.

Assessment-appeal windows are REGISTERED per state and chosen by pack data
(`appeal.window.calendar` in jurisdiction_rules — ADR 0003). Both language
twins are pinned to the same externally verified anchors (Kentucky 2026:
May 4-18), so they cannot drift apart silently. Weekend due dates roll
forward; federal legal holidays are not yet modelled, so an emitted date is
never LATER than the true deadline.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

MIN_YEAR = 1900
MAX_YEAR = 2200


def _check_year(year: int) -> None:
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise ValueError(f"year must be in [{MIN_YEAR}, {MAX_YEAR}], received {year}")


def nth_weekday_of_month(year: int, month: int, weekday: int, nth: int) -> dt.date:
    """The nth occurrence of a weekday in a month — 'first Monday in May'.

    `weekday` uses the stdlib convention (Monday=0 .. Sunday=6, the TS twin
    uses 0=Sunday; both are pinned by the same anchors). A fifth occurrence
    that does not exist in the month is an error, never a silent roll.
    """
    _check_year(year)
    if not 1 <= month <= 12:
        raise ValueError(f"month must be in [1, 12], received {month}")
    if not 0 <= weekday <= 6:
        raise ValueError(f"weekday must be in [0, 6], received {weekday}")
    if not 1 <= nth <= 5:
        raise ValueError(f"nth must be in [1, 5], received {nth}")
    first = dt.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    candidate = first + dt.timedelta(days=offset + (nth - 1) * 7)
    if candidate.month != month:
        raise ValueError(f"{year}-{month:02d} has no occurrence {nth} of weekday {weekday}")
    return candidate


def first_monday_of_may(year: int) -> dt.date:
    return nth_weekday_of_month(year, 5, 0, 1)


class WindowDates(NamedTuple):
    """What a registered appeal-window builder returns for one calendar year.

    conference_by is set only where the state makes a conference a filing
    prerequisite (Kentucky: the PVA conference, KRS 133.120).
    """

    opens_on: dt.date
    closes_on: dt.date
    conference_by: dt.date | None = None


def _ky_open_inspection(year: int) -> WindowDates:
    """KRS 133.045: thirteen days excluding Sundays from the first Monday in
    May — always fifteen calendar days, two Sundays skipped. Anchors: 2026
    May 4-18, 2027 May 3-17."""
    opens = first_monday_of_may(year)
    closes = opens + dt.timedelta(days=14)
    return WindowDates(opens_on=opens, closes_on=closes, conference_by=closes)


# The registry pack data points into: `appeal.window.calendar` rule rows hold
# one of these keys (`us-<state>.<slug>`). A state whose window fits an
# existing builder needs no code here; a novel shape adds one pure builder
# plus anchors, here and in the TypeScript twin (packages/engines/src/
# deadlines.ts). Keys are timeless function identities — a statutory change
# is a NEW key behind a new effective-dated rule row.
#
# Some states belong in NEITHER place. Tennessee's county boards convene on a
# statutory date but adjourn on one each county fixes administratively and
# moves every year — Davidson County was June 14 in 2024, June 27 in 2025,
# June 26 in 2026 — and no statewide list of those dates exists. A builder
# there could only produce a confident wrong answer, so Tennessee has no key
# and its pack carries the published dates as data instead (see
# `appeal.window.closes_on` in seed/907 and the published branch of
# sweep._appeal_windows).
def _oh_bor_complaint(year: int) -> WindowDates:
    """ORC 5715.19(A): a complaint against valuation (DTE Form 1, filed with
    the county auditor as clerk of the Board of Revision) may be filed
    January 1 through March 31 of the year FOLLOWING the tax year — so
    builder(Y) is the window in calendar year Y, contesting tax year Y-1.
    ORC 1.14 extends a weekend deadline to the next business day. No
    conference prerequisite. Anchors: 2027-03-31 (Wednesday) stands;
    2029-03-31 (Saturday) rolls to 2029-04-02."""
    _check_year(year)
    return WindowDates(
        opens_on=dt.date(year, 1, 1),
        closes_on=roll_forward_from_weekend(dt.date(year, 3, 31)),
    )


def _tx_protest_by_may_15(year: int) -> WindowDates:
    """Tex. Tax Code s.41.44(a)(1): a protest is timely "not later than
    May 15 or the 30th day after the date that notice ... was delivered ...
    as provided by Section 25.19, whichever is later" (May 15 text since
    HB 2228, 85th Leg., effective 2018). The
    notice leg is per-parcel and CONDITIONAL (an unchanged value produces no
    notice at all), so this builder emits the date an owner can rely on
    WITHOUT a notice in hand: May 15, extended by s.1.06 off a weekend. A
    later notice-relative deadline is entered from the notice as data, never
    assumed. No statute names an opening date; January 1 is the s.23.01
    valuation date the protest concerns — errs early, never late. The
    s.41.445 informal conference is a right, not a prerequisite. Anchors:
    2026-05-15 (Friday) stands; 2027-05-15 (Saturday) rolls to Monday
    May 17."""
    _check_year(year)
    return WindowDates(
        opens_on=dt.date(year, 1, 1),
        closes_on=roll_forward_from_weekend(dt.date(year, 5, 15)),
    )


APPEAL_WINDOWS: dict[str, Callable[[int], WindowDates]] = {
    "us-ky.open-inspection": _ky_open_inspection,
    "us-oh.bor-complaint": _oh_bor_complaint,
    "us-tx.protest-by-may-15": _tx_protest_by_may_15,
}


def next_window(builder: Callable[[int], WindowDates], as_of: dt.date) -> WindowDates:
    """The next window on or after `as_of`: the close date itself still
    counts — the window is not behind the owner until it has fully passed."""
    current = builder(as_of.year)
    if current.closes_on < as_of:
        return builder(as_of.year + 1)
    return current


@dataclass(frozen=True)
class InspectionWindow:
    opens_on: dt.date
    closes_on: dt.date
    citation: str


def ky_open_inspection_window(year: int) -> InspectionWindow:
    """The Kentucky registry entry with its citation attached — kept as a
    named wrapper because the KY pack's anchor tests pin it (per-state code
    is sanctioned here by ADR 0003)."""
    window = _ky_open_inspection(year)
    return InspectionWindow(
        opens_on=window.opens_on, closes_on=window.closes_on, citation="KRS 133.045"
    )


def next_ky_inspection_window(as_of: dt.date) -> InspectionWindow:
    """The first Kentucky window whose close is not already behind us."""
    window = next_window(_ky_open_inspection, as_of)
    return InspectionWindow(
        opens_on=window.opens_on, closes_on=window.closes_on, citation="KRS 133.045"
    )


def roll_forward_from_weekend(day: dt.date) -> dt.date:
    if day.weekday() == 5:  # Saturday
        return day + dt.timedelta(days=2)
    if day.weekday() == 6:  # Sunday
        return day + dt.timedelta(days=1)
    return day


def federal_estimated_tax_due_dates(tax_year: int) -> list[dt.date]:
    """IRC 6654(c), weekend-rolled."""
    _check_year(tax_year)
    if tax_year >= MAX_YEAR:
        raise ValueError(f"tax_year must be below {MAX_YEAR}")
    raw = [
        dt.date(tax_year, 4, 15),
        dt.date(tax_year, 6, 15),
        dt.date(tax_year, 9, 15),
        dt.date(tax_year + 1, 1, 15),
    ]
    return [roll_forward_from_weekend(day) for day in raw]


def form_1099_nec_due_date(tax_year: int) -> dt.date:
    """IRC 6071(c): January 31 following the tax year, weekend-rolled."""
    _check_year(tax_year)
    if tax_year >= MAX_YEAR:
        raise ValueError(f"tax_year must be below {MAX_YEAR}")
    return roll_forward_from_weekend(dt.date(tax_year + 1, 1, 31))
