"""The jurisdiction coverage report: what the platform knows, per property.

The counterpart of the sweep's gap taxonomy (ADR 0003): where a rule domain
has nothing loaded on a property's chain, this report says so in so many
words instead of letting silence read as safety. The domain list comes from
the database enum itself, so the report grows with the vocabulary and never
hardcodes it.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

import psycopg
from pydantic import BaseModel

from hestia_api import calendar

Conn = psycopg.Connection[dict[str, Any]]


class DomainCoverage(BaseModel):
    status: Literal["covered", "no_rules_loaded"]
    # Present only when covered:
    source: str | None = None
    citation: str | None = None
    calendar_key: str | None = None
    calendar_registered: bool | None = None


class Resolution(BaseModel):
    level: str
    chain: list[str]


class PropertyCoverage(BaseModel):
    property_id: str
    label: str
    state: str
    resolution: Resolution
    domains: dict[str, DomainCoverage]


class CoverageGapOut(BaseModel):
    property_id: str
    state: str
    domain: str
    reason: Literal["no_state_jurisdiction"]
    message: str


class CoverageReport(BaseModel):
    as_of: dt.date
    properties: list[PropertyCoverage]
    gaps: list[CoverageGapOut]


ANCHOR_SQL = """
SELECT p.id AS property_id, p.label, p.state,
       COALESCE(p.jurisdiction_id, s.id) AS start_id
FROM properties p
LEFT JOIN jurisdictions s ON s.level = 'state' AND s.state = p.state
WHERE p.disposed_on IS NULL
ORDER BY p.created_at
"""

CHAIN_SQL = """
SELECT j.name, j.level, c.depth
FROM jurisdiction_chain(%(start_id)s) c
JOIN jurisdictions j ON j.id = c.jurisdiction_id
ORDER BY c.depth
"""

# Most specific body first, newest effective rule, one winner per (domain,
# code) — the same resolution order the sweep uses, by construction of
# jurisdiction_chain.
RULES_SQL = """
SELECT DISTINCT ON (r.domain, r.code)
       r.domain::text AS domain, r.code, r.value_text, r.citation,
       j.name AS source, c.depth
FROM jurisdiction_chain(%(start_id)s) c
JOIN jurisdiction_rules r ON r.jurisdiction_id = c.jurisdiction_id
JOIN jurisdictions j ON j.id = c.jurisdiction_id
WHERE r.superseded_by IS NULL
  AND r.effective_from <= %(as_of)s
  AND (r.effective_to IS NULL OR r.effective_to > %(as_of)s)
ORDER BY r.domain, r.code, c.depth ASC, r.effective_from DESC
"""


def _all_domains(conn: Conn) -> list[str]:
    rows = conn.execute("SELECT unnest(enum_range(NULL::rule_domain))::text AS domain").fetchall()
    return [row["domain"] for row in rows]


def _domain_coverage(rules: list[dict[str, Any]]) -> DomainCoverage:
    """One domain's status from its winning rules.

    The headline rule is the calendar rule where the domain has one (it is
    the rule the sweep acts on, so its citation is the one the owner needs);
    otherwise the most specific rule on the chain.
    """
    head = next(
        (rule for rule in rules if rule["code"].endswith(".calendar")),
        min(rules, key=lambda rule: rule["depth"]),
    )
    coverage = DomainCoverage(status="covered", source=head["source"], citation=head["citation"])
    if head["code"].endswith(".calendar"):
        key = head["value_text"]
        return coverage.model_copy(
            update={
                "calendar_key": key,
                "calendar_registered": key in calendar.APPEAL_WINDOWS,
            }
        )
    return coverage


def report(conn: Conn, as_of: dt.date) -> CoverageReport:
    domains = _all_domains(conn)
    properties: list[PropertyCoverage] = []
    gaps: list[CoverageGapOut] = []
    for anchor in conn.execute(ANCHOR_SQL).fetchall():
        if anchor["start_id"] is None:
            gaps.append(
                CoverageGapOut(
                    property_id=str(anchor["property_id"]),
                    state=anchor["state"],
                    domain="*",
                    reason="no_state_jurisdiction",
                    message=(
                        f"No jurisdiction pack is loaded for {anchor['state']}; "
                        "no jurisdiction-dependent deadlines are generated for "
                        "this property."
                    ),
                )
            )
            continue
        params = {"start_id": anchor["start_id"], "as_of": as_of}
        chain = conn.execute(CHAIN_SQL, params).fetchall()
        by_domain: dict[str, list[dict[str, Any]]] = {}
        for rule in conn.execute(RULES_SQL, params).fetchall():
            by_domain.setdefault(rule["domain"], []).append(rule)
        properties.append(
            PropertyCoverage(
                property_id=str(anchor["property_id"]),
                label=anchor["label"],
                state=anchor["state"],
                resolution=Resolution(
                    level=chain[0]["level"], chain=[link["name"] for link in chain]
                ),
                domains={
                    domain: _domain_coverage(by_domain[domain])
                    if domain in by_domain
                    else DomainCoverage(status="no_rules_loaded")
                    for domain in domains
                },
            )
        )
    return CoverageReport(as_of=as_of, properties=properties, gaps=gaps)
