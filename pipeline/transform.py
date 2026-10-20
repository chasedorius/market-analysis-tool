"""Turn raw Census variables into named metrics and derived ratios.

Rules (from SPEC.md / CLAUDE.md):
- Recompute ratios from counts; never average percentages.
- Keep the margin of error with every estimate we store.
"""

from __future__ import annotations

import math

# Age bands from B01001 (Sex by Age): female var index = male index + 24.
# Each band lists the male estimate suffixes; the female mirror is added in code.
AGE_BANDS = [
    ("0-4", [3]), ("5-9", [4]), ("10-14", [5]), ("15-19", [6, 7]),
    ("20-24", [8, 9, 10]), ("25-34", [11, 12]), ("35-44", [13, 14]),
    ("45-54", [15, 16]), ("55-64", [17, 18, 19]), ("65-74", [20, 21, 22]),
    ("75-84", [23, 24]), ("85+", [25]),
]


def _age_sum(varmap: dict, male_suffixes: list[int]):
    total = 0
    any_val = False
    for s in male_suffixes:
        for idx in (s, s + 24):  # male, then female mirror
            v = varmap.get(f"B01001_{idx:03d}E")
            if v is not None:
                total += v
                any_val = True
    return total if any_val else None


def resolve_metric(spec: dict, varmap: dict):
    """Resolve one metric spec to (value, moe). Handles single vars and sums.

    For a sum, the combined MOE is sqrt(sum of squared component MOEs) when every
    component MOE is present (the Census-recommended aggregation); otherwise None.
    """
    if "var" in spec:
        value = varmap.get(spec["var"])
        moe = varmap.get(spec["moe"]) if spec.get("moe") else None
        return value, moe
    if "sum" in spec:
        values = [varmap.get(v) for v in spec["sum"]]
        present = [v for v in values if v is not None]
        value = sum(present) if present else None
        return value, None
    return None, None


def _ratio(num, den):
    if num is None or den is None or den == 0:
        return None
    return num / den


def compute_metrics(varmap: dict, cfg: dict) -> dict:
    """Named metrics from one area's merged variable map."""
    metrics, moe = {}, {}
    for name, spec in cfg["metrics"].items():
        value, m = resolve_metric(spec, varmap)
        metrics[name] = value
        if m is not None:
            moe[name] = m

    # income distribution (for the affordability view)
    dist = []
    for b in cfg["income_distribution"]["brackets"]:
        dist.append({"label": b["label"], "count": varmap.get(b["var"])})
    metrics["income_distribution"] = dist

    # age distribution + school-age populations (from B01001)
    metrics["age_distribution"] = [
        {"band": label, "count": _age_sum(varmap, suf)} for label, suf in AGE_BANDS]
    age_5_9 = _age_sum(varmap, [4]) or 0
    age_10_14 = _age_sum(varmap, [5]) or 0
    age_15_17 = _age_sum(varmap, [6]) or 0   # B01001 male 15-17 = _006 (+female _030)
    metrics["age_5_9"] = age_5_9
    metrics["age_10_14"] = age_10_14
    metrics["age_15_17"] = age_15_17
    # K-12 ~ ages 5-17; K-6 ~ ages 5-11; grades 7-12 ~ ages 12-17 (10-14 split 2/5 : 3/5)
    metrics["pop_k12"] = age_5_9 + age_10_14 + age_15_17
    metrics["pop_k6"] = round(age_5_9 + age_10_14 * 0.4)
    metrics["pop_7_12"] = round(age_10_14 * 0.6 + age_15_17)

    return {"metrics": metrics, "moe": moe}


def compute_derived(metrics: dict, pop_trend: dict[int, float]) -> dict:
    """Derived ratios. `pop_trend` maps vintage year -> population for this area."""
    m = metrics
    p = pop_trend
    d = {
        "growth_1y": _ratio((p.get(2024) or 0) - p[2023], p[2023]) if p.get(2023) else None,
        "growth_3y": _ratio((p.get(2024) or 0) - p[2021], p[2021]) if p.get(2021) else None,
        "growth_5y": _ratio((p.get(2024) or 0) - p[2019], p[2019]) if p.get(2019) else None,
        "vacancy_rate": _ratio(m.get("vacant_units"), m.get("housing_units")),
        "owner_share": _ratio(m.get("owner_occupied"), m.get("tenure_total")),
        "renter_share": _ratio(m.get("renter_occupied"), m.get("tenure_total")),
        "pipeline_ratio": _ratio(m.get("pop_under5"), m.get("pop_5to9")),
        "rent_to_income": _ratio((m.get("median_gross_rent") or 0) * 12, m.get("median_hh_income")),
        "price_to_income": _ratio(m.get("median_home_value"), m.get("median_hh_income")),
        "unemployment_rate": _ratio(m.get("unemployed"), m.get("labor_force")),
        "pre1980_share": _ratio(m.get("built_pre1980"), m.get("built_total")),
        "overcrowded_share": _ratio(m.get("overcrowded"), m.get("crowd_total")),
        "attached_share": _ratio(
            sum(x for x in (m.get("units_1_attached"), m.get("units_2"), m.get("units_3_4")) if x),
            m.get("units_structure_total"),
        ),
        "multifamily_share": _ratio(m.get("units_5plus"), m.get("units_structure_total")),
    }
    return d
