"""The security deposit: what the jurisdiction requires of it, and returning it.

Kentucky and Ohio rules have been seeded in the packs since module 010 and
nothing consumed them. This does: the duties come from the chain, cited, and
where a chain has nothing to say the answer is a NAMED GAP rather than a
default. A deposit deadline invented from a national average would be worse
than no deadline at all, because it would look like law.

The two regimes the packs already prove apart:
  - Kentucky, KRS 383.580 — the deposit is held in a separate account and the
    tenant gets an itemized list. URLTA binds only where a municipality has
    adopted it, which is why the rule is resolved through the chain and not
    from the state.
  - Ohio, ORC 5321.16 — thirty days to return with an itemization, and 5% per
    annum on the excess over the greater of $50 or one month's rent when the
    deposit has been held six months or more.
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

import psycopg
from pydantic import BaseModel, Field

from hestia_api import ledger as ledger_module

Conn = psycopg.Connection[dict[str, Any]]

CENT = Decimal("0.01")

# ORC 5321.16(A): five per cent per annum, on the amount exceeding the greater
# of fifty dollars or one month's rent, once the deposit has been held six
# months or more. Every number here comes from the statute; none is a default.
OHIO_INTEREST_RATE = Decimal("0.05")
OHIO_EXEMPT_FLOOR = Decimal("50.00")
OHIO_QUALIFYING_MONTHS = 6


class UnknownLease(Exception):
    pass


class AlreadyReturned(Exception):
    pass


class NotMovedOut(Exception):
    """A deposit is returned after the tenancy ends, not during it."""


class ReturnExceedsDeposit(Exception):
    pass


class DutyOut(BaseModel):
    """One thing the jurisdiction requires, and the authority that requires it."""

    code: str
    requirement: str
    citation: str


class GapOut(BaseModel):
    """A duty this chain cannot answer. Named, never defaulted."""

    code: str
    reason: str
    detail: str


class InterestOut(BaseModel):
    accrued: Decimal
    rate: Decimal
    months_held: int
    exempt_amount: Decimal
    interest_bearing: Decimal
    citation: str


class DepositOut(BaseModel):
    lease_id: str
    state: str
    security_deposit: Decimal
    deposit_account: str | None
    moved_out_on: dt.date | None
    deposit_returned_on: dt.date | None
    deposit_returned: Decimal | None
    # Everything below is resolved from the chain, as of the read.
    duties: list[DutyOut]
    gaps: list[GapOut]
    return_days: int | None
    return_due_on: dt.date | None
    return_citation: str | None
    interest: InterestOut | None


class ReturnIn(BaseModel):
    returned_on: dt.date | None = None
    amount: Decimal = Field(ge=0, decimal_places=2, max_digits=18)
    # What was kept and why. A withholding nobody can explain is a withholding
    # nobody can defend.
    withheld_reason: str | None = None
    post_to_ledger: bool = True


class ReturnOut(BaseModel):
    lease_id: str
    returned_on: dt.date
    returned: Decimal
    withheld: Decimal
    withheld_reason: str | None
    ledger_event_uuid: str | None
    deadline_resolved: bool


# The chain's answer for one lease, every security_deposit rule it carries.
_DEPOSIT_RULES = """
WITH lease_anchor AS (
  SELECT l.id AS lease_id, p.state,
         COALESCE(p.jurisdiction_id, s.id) AS start_id
  FROM leases l
  JOIN units u ON u.id = l.unit_id
  JOIN properties p ON p.id = u.property_id
  LEFT JOIN jurisdictions s ON s.level = 'state' AND s.state = p.state
  WHERE l.id = ANY(%(lease_ids)s)
)
SELECT DISTINCT ON (a.lease_id, r.code)
       a.lease_id::text, a.state, r.code, r.value_numeric, r.value_text, r.citation
FROM lease_anchor a
CROSS JOIN LATERAL jurisdiction_chain(a.start_id) c
JOIN jurisdiction_rules r ON r.jurisdiction_id = c.jurisdiction_id
WHERE r.domain = 'security_deposit'
  AND r.superseded_by IS NULL
  AND r.effective_from <= %(as_of)s
  AND (r.effective_to IS NULL OR r.effective_to > %(as_of)s)
ORDER BY a.lease_id, r.code, c.depth ASC, r.effective_from DESC
"""

# How a rule code reads to a human. The text belongs to the pack; this is only
# the sentence that carries it.
_REQUIREMENTS: dict[str, str] = {
    "deposit.return_days": (
        "return the deposit, with an itemization, within {value} days of move-out"
    ),
    "urlta.deposit.separate_account_required": (
        "hold the deposit in a separate account, disclosed to the tenant"
    ),
    "urlta.deposit.itemized_list_required": (
        "give the tenant an itemized list of damages before applying the deposit"
    ),
    "deposit.interest_required": "pay interest on the deposit",
}

# The subset of the above whose VALUE is a truth rather than a quantity. A
# quantity rule states its duty by existing; a boolean one states it only when
# it says true, and says nothing readable at all when it says neither.
_BOOLEAN_DUTIES = frozenset(
    {
        "urlta.deposit.separate_account_required",
        "urlta.deposit.itemized_list_required",
        "deposit.interest_required",
    }
)


def _rule_truth(row: Any) -> bool | None:
    """The truth a boolean rule asserts, or None where it asserts none.

    Presence of the row is not the answer. A pack states both halves — Ohio
    seeds `deposit.interest_required` as "true; 5% per annum ..." and
    Tennessee as "false; ...", because "no duty is owed here" is a finding a
    pack should be able to make and is not the same fact as silence. The
    leading token before any semicolon carries the truth; the prose after it
    carries the reason.

    A row carrying neither token is not a quiet no. It is a rule this build
    cannot read, and the caller names it as a gap rather than guessing which
    way it was meant.

    The sweep asks the same question in SQL (`_deposit_gaps` in sweep.py) and
    must trim the same way, or a panel and a sweep would answer differently
    about one lease.
    """
    asserted = (row["value_text"] or "").strip().lower().split(";")[0].strip()
    if asserted == "true":
        return True
    if asserted == "false":
        return False
    return None


def _reason(row: Any) -> str:
    """The prose a boolean rule carries after its truth token — the pack's own
    words for why it answered as it did."""
    _, _, rest = (row["value_text"] or "").partition(";")
    prose = rest.strip()
    return prose if prose else "the pack states this and gives no further reason"


def _rules_for(conn: Conn, lease_ids: list[str], as_of: dt.date) -> dict[str, list[Any]]:
    rows = conn.execute(_DEPOSIT_RULES, {"lease_ids": lease_ids, "as_of": as_of}).fetchall()
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(row["lease_id"], []).append(row)
    return grouped


def _months_held(start: dt.date, end: dt.date) -> int:
    """Whole months the deposit was held, which is what 'six months or more'
    counts."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(0, months)


def _excess_over_month_rent(
    *, deposit: Decimal, monthly_rent: Decimal, months: int, citation: str
) -> InterestOut:
    """The 'us-oh.excess-over-month-rent' builder — ORC 5321.16(A)."""
    exempt = max(OHIO_EXEMPT_FLOOR, monthly_rent)
    return InterestOut(
        accrued=ohio_interest(
            deposit=deposit,
            monthly_rent=monthly_rent,
            months=months,
            as_of_rate=OHIO_INTEREST_RATE,
        ),
        rate=OHIO_INTEREST_RATE,
        months_held=months,
        exempt_amount=exempt,
        interest_bearing=max(Decimal("0.00"), deposit - exempt),
        citation=citation,
    )


def _interest_formula(key: str | None) -> Any:
    """The registry, keyed by what a pack may name. Built inside the lookup so
    a new state is a seed row plus a builder, never a branch."""
    registry = {"us-oh.excess-over-month-rent": _excess_over_month_rent}
    return registry.get(key) if key is not None else None


def ohio_interest(
    *, deposit: Decimal, monthly_rent: Decimal, months: int, as_of_rate: Decimal
) -> Decimal:
    """ORC 5321.16(A). Interest runs only on the excess over the GREATER of
    fifty dollars or one month's rent, and only once the deposit has been held
    six months or more."""
    if months < OHIO_QUALIFYING_MONTHS:
        return Decimal("0.00")
    exempt = max(OHIO_EXEMPT_FLOOR, monthly_rent)
    bearing = deposit - exempt
    if bearing <= 0:
        return Decimal("0.00")
    return (bearing * as_of_rate * Decimal(months) / Decimal(12)).quantize(
        CENT, rounding=ROUND_HALF_EVEN
    )


def read(conn: Conn, lease_id: str, *, as_of: dt.date) -> DepositOut:
    lease = conn.execute(
        """
        SELECT l.id::text, p.state, l.security_deposit, l.deposit_account,
               l.moved_out_on, l.deposit_returned_on, l.deposit_returned,
               l.rent, l.starts_on
        FROM leases l
        JOIN units u ON u.id = l.unit_id
        JOIN properties p ON p.id = u.property_id
        WHERE l.id = %s
        """,
        (lease_id,),
    ).fetchone()
    if lease is None:
        raise UnknownLease(lease_id)

    rules = _rules_for(conn, [lease_id], as_of).get(lease_id, [])
    by_code = {row["code"]: row for row in rules}

    duties: list[DutyOut] = []
    gaps: list[GapOut] = []
    for code, row in sorted(by_code.items()):
        template = _REQUIREMENTS.get(code)
        if template is None:
            continue  # a pack may carry codes this release has no sentence for
        if code in _BOOLEAN_DUTIES:
            truth = _rule_truth(row)
            if truth is None:
                # The row exists and this build cannot read it. Printing the
                # duty anyway would assert an obligation nobody stated, and
                # dropping it silently would hide a broken pack.
                gaps.append(
                    GapOut(
                        code=code,
                        reason="unreadable_rule_value",
                        detail=(
                            f"{row['citation']} carries neither true nor false, so "
                            "whether this duty attaches cannot be read from the "
                            "pack; it is not guessed either way"
                        ),
                    )
                )
                continue
            if not truth:
                continue  # the pack says this duty does not attach here
        value = row["value_numeric"] if row["value_numeric"] is not None else row["value_text"]
        duties.append(
            DutyOut(
                code=code,
                requirement=template.format(value=value),
                citation=row["citation"],
            )
        )

    return_rule = by_code.get("deposit.return_days")
    return_days = int(return_rule["value_numeric"]) if return_rule else None
    if return_rule is None:
        # "This state fixes no deadline" and "we have loaded no deadline for
        # this state" are different answers and must not read alike. Where a
        # pack states the absence — Tennessee's chapter gives a forfeiture
        # rule instead of a due date — the panel carries that rule and raises
        # no gap. Silence still raises one.
        stated_absent = by_code.get("deposit.return_deadline_exists")
        if stated_absent is not None and _rule_truth(stated_absent) is False:
            duties.append(
                DutyOut(
                    code=stated_absent["code"],
                    requirement=_reason(stated_absent),
                    citation=stated_absent["citation"],
                )
            )
        else:
            gaps.append(
                GapOut(
                    code="deposit.return_days",
                    reason="no_rule_for_domain",
                    detail=(
                        f"no deposit return period is seeded for {lease['state']}; the "
                        "deadline is not invented and the lease terms govern until a "
                        "pack says otherwise"
                    ),
                )
            )
    return_due = (
        lease["moved_out_on"] + dt.timedelta(days=return_days)
        if return_days is not None and lease["moved_out_on"] is not None
        else None
    )

    interest: InterestOut | None = None
    # An unreadable value already produced its gap in the duties loop above.
    interest_rule = by_code.get("deposit.interest_required")
    if interest_rule is not None and _rule_truth(interest_rule):
        # WHICH formula is a rule too (ADR 0003): the pack names a registered
        # builder and the code never branches on a state literal.
        formula_rule = by_code.get("deposit.interest_formula")
        key = formula_rule["value_text"] if formula_rule else None
        builder = _interest_formula(key)
        if builder is None:
            gaps.append(
                GapOut(
                    code="deposit.interest_formula",
                    reason=("no_formula_rule" if key is None else "formula_key_unregistered"),
                    detail=(
                        f"{interest_rule['citation']} requires deposit interest but "
                        + (
                            "the pack names no formula"
                            if key is None
                            else f"no builder is registered for {key!r}"
                        )
                        + "; the amount is not guessed"
                    ),
                )
            )
        else:
            interest = builder(
                deposit=lease["security_deposit"],
                monthly_rent=lease["rent"],
                months=_months_held(lease["starts_on"], lease["moved_out_on"] or as_of),
                citation=formula_rule["citation"],
            )

    return DepositOut(
        lease_id=lease["id"],
        state=lease["state"],
        security_deposit=lease["security_deposit"],
        deposit_account=lease["deposit_account"],
        moved_out_on=lease["moved_out_on"],
        deposit_returned_on=lease["deposit_returned_on"],
        deposit_returned=lease["deposit_returned"],
        duties=duties,
        gaps=gaps,
        return_days=return_days,
        return_due_on=return_due,
        return_citation=return_rule["citation"] if return_rule else None,
        interest=interest,
    )


def return_deposit(conn: Conn, lease_id: str, body: ReturnIn) -> ReturnOut:
    """The money, the record and the deadline, in one transaction."""
    lease = conn.execute(
        """
        SELECT l.id::text, l.security_deposit, l.moved_out_on, l.deposit_returned_on,
               u.property_id::text, p.entity_id::text
        FROM leases l
        JOIN units u ON u.id = l.unit_id
        JOIN properties p ON p.id = u.property_id
        WHERE l.id = %s FOR UPDATE OF l
        """,
        (lease_id,),
    ).fetchone()
    if lease is None:
        raise UnknownLease(lease_id)
    if lease["deposit_returned_on"] is not None:
        raise AlreadyReturned(str(lease["deposit_returned_on"]))
    if lease["moved_out_on"] is None:
        raise NotMovedOut(lease_id)
    if body.amount > lease["security_deposit"]:
        raise ReturnExceedsDeposit(str(lease["security_deposit"]))

    returned_on = body.returned_on or dt.date.today()
    withheld = lease["security_deposit"] - body.amount
    conn.execute(
        """
        UPDATE leases SET deposit_returned_on = %s, deposit_returned = %s
        WHERE id = %s
        """,
        (returned_on, body.amount, lease_id),
    )
    event_uuid: str | None = None
    if body.post_to_ledger and body.amount > 0:
        event = ledger_module.append_event(
            conn,
            ledger_module.LedgerEntryIn(
                occurred_on=returned_on,
                category="deposit_returned",
                amount=-body.amount,
                memo=body.withheld_reason or "security deposit returned",
                property_id=lease["property_id"],
                lease_id=lease_id,
                entity_id=lease["entity_id"],
            ),
        )
        event_uuid = event.event_uuid
    resolved = conn.execute(
        """
        UPDATE deadlines SET status = 'done', completed_on = %s
        WHERE lease_id = %s AND kind::text = 'deposit_itemization' AND status = 'upcoming'
        """,
        (returned_on, lease_id),
    )
    return ReturnOut(
        lease_id=lease_id,
        returned_on=returned_on,
        returned=body.amount,
        withheld=withheld,
        withheld_reason=body.withheld_reason,
        ledger_event_uuid=event_uuid,
        deadline_resolved=resolved.rowcount > 0,
    )


def list_open(conn: Conn, *, as_of: dt.date) -> list[DepositOut]:
    """Every tenancy that has ended without the deposit being settled."""
    rows = conn.execute(
        """
        SELECT id::text FROM leases
        WHERE moved_out_on IS NOT NULL AND deposit_returned_on IS NULL
        ORDER BY moved_out_on
        """,
    ).fetchall()
    return [read(conn, row["id"], as_of=as_of) for row in rows]
