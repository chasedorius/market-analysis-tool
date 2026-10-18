"""Composite scores: average percentile rank of each score's inputs among the
peer set (Phase 1 = Davis County cities). Formulas are defined in config/scores.yaml.
"""

from __future__ import annotations


def percentile_ranks(values: dict[str, float]) -> dict[str, float]:
    """Map geoid -> percentile (0-100), ascending, average ranks for ties.

    None values stay None. A single present value scores 50 (no spread to rank).
    """
    present = sorted(((g, v) for g, v in values.items() if v is not None),
                     key=lambda kv: kv[1])
    n = len(present)
    if n == 0:
        return {g: None for g in values}
    if n == 1:
        return {g: (50.0 if values[g] is not None else None) for g in values}

    avg_rank: dict[str, float] = {}
    j = 0
    while j < n:
        k = j
        while k + 1 < n and present[k + 1][1] == present[j][1]:
            k += 1
        rank = (j + k) / 2.0  # 0-based average rank for the tie group
        for idx in range(j, k + 1):
            avg_rank[present[idx][0]] = rank
        j = k + 1

    return {g: (avg_rank[g] / (n - 1) * 100.0 if v is not None else None)
            for g, v in values.items()}


def _input_spec(inp):
    if isinstance(inp, dict):
        return inp["metric"], bool(inp.get("invert", False))
    return inp, False


def build_scores(area_values: dict[str, dict], scores_cfg: dict) -> dict[str, dict]:
    """area_values: {geoid: {metric_name: value}} (metrics + derived, merged).

    Returns {geoid: {"scores": {...}, "input_pct": {...}}}.
    """
    geoids = list(area_values)
    pct_cache: dict[str, dict] = {}

    def pct_for(metric: str) -> dict:
        if metric not in pct_cache:
            vals = {g: area_values[g].get(metric) for g in geoids}
            pct_cache[metric] = percentile_ranks(vals)
        return pct_cache[metric]

    out = {g: {"scores": {}, "input_pct": {}} for g in geoids}
    for sname, sdef in scores_cfg["scores"].items():
        if sdef.get("status") == "pending_data":
            for g in geoids:
                out[g]["scores"][sname] = None
            continue
        inputs = [_input_spec(i) for i in sdef["inputs"]]
        for g in geoids:
            parts = []
            for metric, invert in inputs:
                pct = pct_for(metric).get(g)
                if pct is None:
                    continue
                if invert:
                    pct = 100.0 - pct
                parts.append(pct)
                out[g]["input_pct"][f"{metric}{'(inv)' if invert else ''}"] = round(pct, 1)
            out[g]["scores"][sname] = round(sum(parts) / len(parts), 1) if parts else None
    return out
