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


def _tn_county_board(year: int) -> WindowDates:
    """Tennessee's assessment-contest window, in the counties that keep the
    statewide calendar.

    TCA 67-1-404(a): the county board of equalization meets on June 1 each
    year and sits until equalization is complete. The Comptroller, which
    supervises the boards, states the board convenes the next business day
    where June 1 falls on a weekend, so the OPEN rolls too — unlike Ohio's,
    where the open is a statutory date rather than a meeting.

    TCA 67-5-1412(e): an appeal from the local board reaches the State Board
    of Equalization only if filed by August 1 of the tax year, or within
    forty-five days of the date notice of the local board's action was sent,
    whichever is later. The forty-five-day leg depends on a notice this
    system has not seen, so the builder returns the date every Tennessee
    owner can rely on WITHOUT one — never later than the true deadline.

    TCA 1-3-102 excludes a last day falling on a Saturday, Sunday or legal
    holiday. Anchors: 2028-08-01 is a Tuesday and stands; 2027-08-01 is a
    Sunday and rolls to 2027-08-02.
    """
    _check_year(year)
    return WindowDates(
        opens_on=roll_forward_from_weekend(dt.date(year, 6, 1)),
        closes_on=roll_forward_from_weekend(dt.date(year, 8, 1)),
    )


def _tn_shelby_county_board(year: int) -> WindowDates:
    """Shelby County (Memphis) convenes May 1, a month ahead of the rest of
    Tennessee — a county-level fact, so the pack overrides the state's
    calendar on the Shelby County row and the chain does the rest. The close
    is unchanged: TCA 67-5-1412(e) is statewide.

    Authority is the Comptroller's published county-board schedule rather
    than TCA 67-1-404 itself, which is why this is a separate key and not a
    parameter — a builder whose two callers disagree about their source
    would be one function pretending to be two rules. Anchors: 2027-05-01 is
    a Saturday and rolls to 2027-05-03; 2028-05-01 is a Monday and stands.
    """
    _check_year(year)
    return WindowDates(
        opens_on=roll_forward_from_weekend(dt.date(year, 5, 1)),
        closes_on=roll_forward_from_weekend(dt.date(year, 8, 1)),
    )


APPEAL_WINDOWS: dict[str, Callable[[int], WindowDates]] = {
    "us-ky.open-inspection": _ky_open_inspection,
    "us-oh.bor-complaint": _oh_bor_complaint,
    "us-tn.county-board": _tn_county_board,
    "us-tn.shelby-county-board": _tn_shelby_county_board,
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
