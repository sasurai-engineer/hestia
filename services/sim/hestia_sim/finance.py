"""Reference financial arithmetic, independent of the TypeScript engines.

Everything is exact: amounts are integer cents, percentages are
``fractions.Fraction``, and the one rounding primitive mirrors the TypeScript
``divideRound`` semantics so the two implementations are comparable digit for
digit. Where the TypeScript side uses decimal.js at 40 significant digits
(discounting), this side uses ``decimal.Decimal`` at the same precision — a
different library arriving at the same correctly-rounded answer.
"""

from __future__ import annotations

from decimal import Decimal, getcontext
from fractions import Fraction

getcontext().prec = 40

HALF_UP = "HALF_UP"
HALF_EVEN = "HALF_EVEN"


def div_round(numerator: int, denominator: int, mode: str) -> int:
    """Integer division rounded under ``mode`` — the TS ``divideRound`` twin."""
    if denominator == 0:
        raise ZeroDivisionError("division by zero")
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    quotient, remainder = divmod(numerator, denominator)  # floors toward -inf
    if remainder == 0:
        return quotient
    twice = remainder * 2
    if mode == HALF_UP:
        # Python divmod floors, so quotient+1 is always the away-from-zero
        # neighbour for positive denominators; ties on negatives need care.
        if numerator >= 0:
            return quotient + 1 if twice >= denominator else quotient
        return quotient + 1 if twice > denominator else quotient
    if mode != HALF_EVEN:
        raise ValueError(f"unsupported mode {mode!r}")
    if twice > denominator:
        return quotient + 1
    if twice < denominator:
        return quotient
    return quotient if quotient % 2 == 0 else quotient + 1


def round_cents(value: Fraction, mode: str) -> int:
    """Round an exact cents value to an integer number of cents."""
    return div_round(value.numerator, value.denominator, mode)


def amortization(principal_cents: int, annual_rate: str, term_months: int) -> dict:
    """Level-payment schedule; HalfUp per the lender convention."""
    if principal_cents <= 0 or term_months <= 0:
        raise ValueError("principal and term must be positive")
    monthly = Fraction(Decimal(annual_rate)) / 12
    if monthly == 0:
        base, extra = divmod(principal_cents, term_months)
        payment = base + (1 if extra else 0)
    else:
        # payment = P * i / (1 - (1+i)^-n), the discount factor at 40 digits.
        one_plus = Decimal(1) + Decimal(annual_rate) / 12
        discount = Fraction(Decimal(1) / (one_plus**term_months))
        factor = monthly / (1 - discount)
        payment = round_cents(principal_cents * factor, HALF_UP)

    rows = []
    balance = principal_cents
    total_interest = 0
    for month in range(1, term_months + 1):
        interest = round_cents(balance * monthly, HALF_UP)
        principal_part = balance if month == term_months else payment - interest
        principal_part = min(principal_part, balance)
        balance -= principal_part
        total_interest += interest
        rows.append(
            {
                "month": month,
                "payment": interest + principal_part,
                "interest": interest,
                "principal": principal_part,
                "balance": balance,
            }
        )
    # The invariants -- zero final balance, principal parts summing exactly --
    # hold by construction and are asserted by the test suite, where a breach
    # is visible; dead defensive raises only hide from coverage.
    return {"payment": payment, "rows": rows, "total_interest": total_interest}


def first_year_fraction(convention: str, month: int | None, quarter: int | None) -> Fraction:
    if convention == "mid_month":
        if month is None or not 1 <= month <= 12:
            raise ValueError("mid_month needs a month 1-12")
        return Fraction(2 * (12 - month) + 1, 24)
    if convention == "mid_quarter":
        if quarter is None or not 1 <= quarter <= 4:
            raise ValueError("mid_quarter needs a quarter 1-4")
        return Fraction(2 * (4 - quarter) + 1, 8)
    if convention == "half_year":
        return Fraction(1, 2)
    raise ValueError(f"unknown convention {convention!r}")


def macrs_percents(
    life: str,
    method: str,
    convention: str,
    month: int | None = None,
    quarter: int | None = None,
) -> list[Fraction]:
    """Exact yearly fractions of the depreciable base; they sum to one."""
    life_f = Fraction(Decimal(life))
    first = first_year_fraction(convention, month, quarter)
    if method == "macrs_sl":
        full = 1 / life_f
        pcts = [full * first]
        open_pct = 1 - pcts[0]
        while open_pct > 0:
            ded = full if open_pct > full else open_pct
            pcts.append(ded)
            open_pct -= ded
        return pcts
    factor = {"macrs_200db": Fraction(2), "macrs_150db": Fraction(3, 2)}[method]
    db_rate = factor / life_f
    pcts = [db_rate * first]
    open_pct = 1 - pcts[0]
    remaining_life = life_f - first
    # Declining balance always terminates through the plug year, so the loop is
    # `while True`. No `switched` flag: once straight-line on the remaining
    # basis meets declining balance it stays ahead, so the comparison alone is
    # the statutory switch.
    while True:
        if remaining_life <= 1:
            pcts.append(open_pct)
            break
        db = open_pct * db_rate
        sl = open_pct / remaining_life
        ded = sl if sl >= db else db
        pcts.append(ded)
        open_pct -= ded
        remaining_life -= 1
    return pcts


def depreciate(
    basis_cents: int,
    method: str,
    life: str,
    convention: str,
    bonus: Fraction,
    s179_cents: int,
    month: int | None = None,
    quarter: int | None = None,
) -> dict:
    """§179 first, bonus on the remainder, MACRS on the rest; exact totals."""
    if basis_cents <= 0 or not 0 <= s179_cents <= basis_cents or not 0 <= bonus <= 1:
        raise ValueError("invalid elections")
    after_179 = basis_cents - s179_cents
    bonus_cents = round_cents(after_179 * bonus, HALF_EVEN)
    macrs_base = after_179 - bonus_cents
    schedule: list[int] = []
    if macrs_base > 0:
        pcts = macrs_percents(life, method, convention, month, quarter)
        accumulated = 0
        for index, pct in enumerate(pcts):
            if index == len(pcts) - 1:
                amount = macrs_base - accumulated
            else:
                amount = round_cents(macrs_base * pct, HALF_EVEN)
            accumulated += amount
            schedule.append(amount)
    total = s179_cents + bonus_cents + sum(schedule)
    return {"section179": s179_cents, "bonus": bonus_cents, "schedule": schedule, "total": total}


def section179_limit(
    total_placed_in_service_cents: int, cap_cents: int, phaseout_start_cents: int
) -> int:
    """A state's s179 regime as parameters: a cap with dollar-for-dollar
    phaseout above a threshold. The numbers come from jurisdiction_rules pack
    data (ADR 0003); the arithmetic lives here where it is differential-tested
    against the TypeScript twin."""
    if total_placed_in_service_cents < 0:
        raise ValueError("total placed in service must not be negative")
    excess = max(0, total_placed_in_service_cents - phaseout_start_cents)
    return max(0, cap_cents - excess)


# Kentucky's profile (IRC s.168 as of 2001-12-31). The authoritative copy is
# the seed pack row; tests/packs/kentucky.sql and the shared fixture rows pin
# the copies together in CI.
KY_2001_S179_CAP_CENTS = 25_000_00
KY_2001_S179_PHASEOUT_START_CENTS = 200_000_00


def ky_section179_limit(total_placed_in_service_cents: int) -> int:
    return section179_limit(
        total_placed_in_service_cents,
        KY_2001_S179_CAP_CENTS,
        KY_2001_S179_PHASEOUT_START_CENTS,
    )


def state_addback_schedule(
    accelerated_cents: int, numerator: int, denominator: int, recovery_years: int
) -> dict:
    """Addback-recovery conformity (e.g. Ohio ORC 5747.01: 2/3 add-back,
    six-year recovery): the state disallows a fraction of federal accelerated
    depreciation in year one and returns it in equal later slices. Exact
    rational arithmetic, one HalfEven rounding per figure, and a final-year
    plug in money space so the recovery slices sum to the addback exactly.
    """
    if accelerated_cents < 0:
        raise ValueError("accelerated depreciation must not be negative")
    if not 1 <= numerator <= denominator:
        raise ValueError("addback numerator must be in [1, denominator]")
    if not 1 <= recovery_years <= 100:
        raise ValueError("recovery_years must be in [1, 100]")
    addback = round_cents(Fraction(accelerated_cents * numerator, denominator), HALF_EVEN)
    per_year = round_cents(Fraction(addback, recovery_years), HALF_EVEN)
    recovery = [per_year] * (recovery_years - 1)
    recovery.append(addback - per_year * (recovery_years - 1))
    return {"addback": addback, "recovery": recovery}


def npv_cents(rate: str, flows_cents: list[int]) -> int:
    """Each term discounted at 40 digits and rounded HalfEven once."""
    one_plus = Decimal(1) + Decimal(rate)
    total = flows_cents[0]
    for t, flow in enumerate(flows_cents[1:], start=1):
        discount = Fraction(Decimal(1) / (one_plus**t))
        total += round_cents(flow * discount, HALF_EVEN)
    return total


def irr(flows_cents: list[int], iterations: int = 120) -> Decimal:
    """Bisection twin of the TypeScript engine: same bracket, same stop."""
    if not any(f < 0 for f in flows_cents) or not any(f > 0 for f in flows_cents):
        raise ValueError("irr needs at least one inflow and one outflow")
    lo, hi = Decimal("-0.9999"), Decimal("10")

    def sign(r: Decimal) -> int:
        value = npv_cents(str(r), flows_cents)
        return 0 if value == 0 else (-1 if value < 0 else 1)

    s_lo, s_hi = sign(lo), sign(hi)
    if s_lo == 0:
        return lo
    if s_hi == 0:
        return hi
    if s_lo == s_hi:
        raise ValueError("irr has no root in the bracket")
    for _ in range(iterations):
        mid = (lo + hi) / 2
        s_mid = sign(mid)
        if s_mid == 0:
            return mid
        if s_mid == s_lo:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def renewal_ev(
    rent_cents: int, turn_cents: int, vacancy_days: int, increase_cents: int, p_stay: Fraction
) -> dict:
    """The renewal expected-value twin, mirroring each rounding step."""
    daily = div_round(rent_cents * 12, 365, HALF_EVEN)
    gain = round_cents(Fraction(increase_cents * 12) * p_stay, HALF_EVEN)
    vacancy_loss = vacancy_days * daily
    loss = round_cents(Fraction(turn_cents + vacancy_loss) * (1 - p_stay), HALF_EVEN)
    return {"expected_gain": gain, "expected_turn_loss": loss, "expected_value": gain - loss}


def coinsurance(
    loss_cents: int,
    carried_cents: int,
    replacement_cents: int,
    coinsurance_pct: Fraction,
    deductible_cents: int,
) -> dict:
    required = round_cents(replacement_cents * coinsurance_pct, HALF_UP)
    if required == 0 or carried_cents >= required:
        factor = Fraction(1)
    else:
        # Mirror the TypeScript ratio(): the quotient is rounded to 40
        # significant digits before it multiplies the loss, so a
        # non-terminating ratio cannot diverge between the two languages.
        factor = Fraction(Decimal(carried_cents) / Decimal(required))
    covered = round_cents(loss_cents * factor, HALF_EVEN)
    recovery = max(0, min(covered - deductible_cents, carried_cents))
    return {"recovery": recovery, "retained": loss_cents - recovery}


def disposal(
    sale_cents: int, costs_cents: int, basis_cents: int, depreciation_cents: int, kind: str
) -> dict:
    realized = sale_cents - costs_cents
    adjusted = basis_cents - depreciation_cents
    gain = realized - adjusted
    if gain <= 0:
        return {
            "gain": 0,
            "loss": -gain,
            "ordinary_1245": 0,
            "unrecaptured_1250": 0,
            "capital_gain": 0,
        }
    recaptured = min(gain, depreciation_cents)
    personal = kind == "personal_property"
    return {
        "gain": gain,
        "loss": 0,
        "ordinary_1245": recaptured if personal else 0,
        "unrecaptured_1250": 0 if personal else recaptured,
        "capital_gain": gain - recaptured,
    }
