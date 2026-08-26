"""The onboarding inference engine — steps 8 and 9 of the dossier.

Every incumbent asks the owner to type in forty install dates they do not
know, so the table stays empty and the capital plan stays a guess. This module
infers the component inventory from vintage, permit history and the seeded
catalog, and derives the latent-defect register from construction era — each
output carrying the provenance posture the schema demands: a permit-backed
date is `public_record`; a vintage heuristic is `inferred` with its reasoning
in prose; nothing is presented as more certain than it is.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# The inference catalog: code -> (life_low, life_high) years.
#
# These bands MUST agree with packages/domain/schema/seed/901_component_catalog
# .sql — a test parses that file and fails on any divergence, so the inference
# and the capex simulation can never quietly reason from different lifetimes.
# ---------------------------------------------------------------------------
CATALOG_LIVES: dict[str, tuple[float, float]] = {
    "roof.asphalt_shingle.architectural": (15, 25),
    "hvac.furnace.gas": (15, 20),
    "hvac.condenser.ac": (12, 18),
    "water_heater.tank": (8, 12),
    "electrical.panel": (25, 40),
    "life_safety.smoke_co_detector": (8, 10),
    "exterior.paint": (5, 10),
    "windows_doors.windows.vinyl": (20, 30),
    "appliance.refrigerator": (10, 13),
    "appliance.dishwasher": (9, 10),
    "appliance.range": (13, 15),
}

#: What a permit's trade maps to, when the county feed categorises them.
PERMIT_KIND_TO_CODE: dict[str, str] = {
    "roof": "roof.asphalt_shingle.architectural",
    "hvac": "hvac.furnace.gas",
    "water_heater": "water_heater.tank",
    "electrical": "electrical.panel",
    "windows": "windows_doors.windows.vinyl",
}


@dataclass(frozen=True)
class PermitRecord:
    kind: str  # a key of PERMIT_KIND_TO_CODE, or anything else (ignored)
    issued_year: int


@dataclass(frozen=True)
class InferredComponent:
    type_code: str
    installed_year_low: int
    installed_year_high: int
    provenance_kind: str  # 'public_record' | 'inferred'
    confidence: float
    derived_from: str


@dataclass(frozen=True)
class DefectFlag:
    kind: str  # matches the schema's defect_kind enum
    affects_safety: bool
    affects_insurance: bool
    affects_financing: bool
    triggers_disclosure: bool
    citation: str | None
    derived_from: str


def _validate_years(year_built: int, observed_year: int) -> None:
    if not 1600 <= year_built <= 2200:
        raise ValueError(f"year_built out of range: {year_built}")
    if observed_year < year_built:
        raise ValueError("observed_year cannot precede year_built")
    if observed_year > 2200:
        raise ValueError(f"observed_year out of range: {observed_year}")


def infer_components(
    year_built: int,
    observed_year: int,
    permits: list[PermitRecord] | None = None,
) -> list[InferredComponent]:
    """One inferred row per catalog system, permits trumping vintage.

    The vintage heuristic is deliberately humble: a component younger than its
    minimum life is presumed original; anything older has been replaced at
    least once, somewhere in the last full life band — a wide band with modest
    confidence, which still forecasts better than no component at all.
    """
    _validate_years(year_built, observed_year)
    latest_permit: dict[str, int] = {}
    for permit in permits or []:
        code = PERMIT_KIND_TO_CODE.get(permit.kind)
        if code is None:
            continue
        if not year_built <= permit.issued_year <= observed_year:
            raise ValueError(
                f"permit year {permit.issued_year} outside [{year_built}, {observed_year}]"
            )
        latest_permit[code] = max(latest_permit.get(code, permit.issued_year), permit.issued_year)

    inferred: list[InferredComponent] = []
    for code, (life_low, life_high) in sorted(CATALOG_LIVES.items()):
        permit_year = latest_permit.get(code)
        if permit_year is not None:
            inferred.append(
                InferredComponent(
                    type_code=code,
                    installed_year_low=permit_year,
                    installed_year_high=permit_year,
                    provenance_kind="public_record",
                    confidence=0.9,
                    derived_from=f"permit issued {permit_year}",
                )
            )
            continue
        age = observed_year - year_built
        if age <= life_low:
            inferred.append(
                InferredComponent(
                    type_code=code,
                    installed_year_low=year_built,
                    installed_year_high=year_built,
                    provenance_kind="inferred",
                    confidence=0.75,
                    derived_from=(
                        f"building age {age} is within the component's minimum life "
                        f"{life_low:g}; presumed original"
                    ),
                )
            )
        else:
            low = max(year_built, observed_year - int(life_high))
            inferred.append(
                InferredComponent(
                    type_code=code,
                    installed_year_low=low,
                    installed_year_high=observed_year,
                    provenance_kind="inferred",
                    confidence=0.5,
                    derived_from=(
                        f"building age {age} exceeds the component's minimum life "
                        f"{life_low:g}; replaced at least once, within the last "
                        f"{life_high:g} years"
                    ),
                )
            )
    return inferred


# ---------------------------------------------------------------------------
# Latent defects by construction era.
#
# Era bounds follow the schema's own register (002_property.sql): each entry is
# (kind, first_year, last_year, safety, insurance, financing, disclosure,
# citation). A None citation means the flag rests on a vintage heuristic and
# says so; only the lead-paint duty carries statutory authority here.
# ---------------------------------------------------------------------------
_ERA_RULES: list[tuple[str, int | None, int | None, bool, bool, bool, bool, str | None]] = [
    (
        "lead_paint",
        None,
        1977,
        True,
        False,
        False,
        True,
        "42 U.S.C. s.4852d (disclosure); EPA RRP, 40 CFR Part 745 (renovation)",
    ),
    ("asbestos", None, 1979, True, True, False, True, None),
    ("aluminium_branch_wiring", 1965, 1973, True, True, True, False, None),
    ("polybutylene_supply", 1978, 1995, False, True, True, False, None),
    ("orangeburg_sewer", 1945, 1972, False, False, True, False, None),
    ("galvanized_supply", None, 1959, False, True, True, False, None),
    ("knob_and_tube", None, 1949, True, True, True, False, None),
    ("cast_iron_drain", None, 1974, False, True, False, False, None),
]


def infer_latent_defects(year_built: int, observed_year: int) -> list[DefectFlag]:
    """The vintage risks worth a 'suspected' row — never a confirmation."""
    _validate_years(year_built, observed_year)
    flags: list[DefectFlag] = []
    for kind, first, last, safety, insurance, financing, disclosure, citation in _ERA_RULES:
        if first is not None and year_built < first:
            continue
        if last is not None and year_built > last:
            continue
        span = (
            f"built {year_built}, within the {kind.replace('_', ' ')} era ({first or 'pre'}-{last})"
        )
        flags.append(
            DefectFlag(
                kind=kind,
                affects_safety=safety,
                affects_insurance=insurance,
                affects_financing=financing,
                triggers_disclosure=disclosure,
                citation=citation,
                derived_from=span,
            )
        )
    return flags
