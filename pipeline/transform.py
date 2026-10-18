"""Turn raw Census variables into named metrics and derived ratios.

Rules (from SPEC.md / CLAUDE.md):
- Recompute ratios from counts; never average percentages.
- Keep the margin of error with every estimate we store.
"""

from __future__ import annotations

import math


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
