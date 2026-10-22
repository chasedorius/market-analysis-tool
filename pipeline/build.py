"""Phase 1 build: fetch -> transform -> score -> write JSON.

Run from the repo root:
    .\\.venv\\Scripts\\python.exe -m pipeline.build
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from pipeline.census_client import CensusClient, geoid_of, load_env
from pipeline.crosswalks import load_crosswalk
from pipeline.scores import build_scores
from pipeline.transform import compute_derived, compute_metrics

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"


def load_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG / name).read_text(encoding="utf-8"))


def _round_floats(o, nd=5):
    """Round floats to shrink JSON (display formatting rounds anyway)."""
    if isinstance(o, float):
        return round(o, nd)
    if isinstance(o, dict):
        return {k: _round_floats(v, nd) for k, v in o.items()}
    if isinstance(o, list):
        return [_round_floats(v, nd) for v in o]
    return o


def _compact(obj) -> str:
    return json.dumps(_round_floats(obj), separators=(",", ":"))


def fetch_level(client, year, tables, for_geo, in_geo=None) -> dict[str, dict]:
    """Merge every table group for one geography level into {geoid: varmap}."""
    merged: dict[str, dict] = {}
    for table in tables:
        for row in client.fetch_group(year, table, for_geo, in_geo):
            merged.setdefault(geoid_of(row), {}).update(row)
    return merged


# Tables + years for the per-year trend chart (a focused subset, pulled across
# vintages). Population plus the inputs to the ratios shown over time.
SERIES_TABLES = ["B01003", "B19013", "B25064", "B25077", "B25002", "B23025"]
SERIES_YEARS = [2019, 2020, 2021, 2022, 2023, 2024]


def _series_point(vm: dict) -> dict:
    """One year's snapshot of the metrics/ratios shown on the trend chart."""
    g = vm.get
    pop, inc, rent = g("B01003_001E"), g("B19013_001E"), g("B25064_001E")
    val, hu, vac = g("B25077_001E"), g("B25002_001E"), g("B25002_003E")
    lf, unemp = g("B23025_003E"), g("B23025_005E")

    def ratio(a, b):
        return a / b if (a is not None and b not in (None, 0)) else None

    return {
        "population": pop,
        "median_hh_income": inc,
        "median_gross_rent": rent,
        "median_home_value": val,
        "vacancy_rate": ratio(vac, hu),
        "unemployment_rate": ratio(unemp, lf),
        "rent_to_income": ratio(rent * 12 if rent else None, inc),
        "price_to_income": ratio(val, inc),
    }


def build_series(client, years, state) -> dict[str, dict]:
    """{geoid: {year: snapshot}} for the state, all counties, and all places."""
    out: dict[str, dict] = {}
    levels = [(f"state:{state}", None),
              ("county:*", f"state:{state}"),
              ("place:*", f"state:{state}")]
    for year in years:
        for for_geo, in_geo in levels:
            vmap = fetch_level(client, year, SERIES_TABLES, for_geo, in_geo)
            for gid, vm in vmap.items():
                out.setdefault(gid, {})[str(year)] = _series_point(vm)
    return out


def main() -> None:
    load_env()
    sources = load_yaml("sources.yaml")
    geography = load_yaml("geography.yaml")
    scores_cfg = load_yaml("scores.yaml")

    acs = sources["dataset"]["acs5"]
    year = acs["current_vintage"]
    trend_vintages = acs["trend_vintages"]
    tables = list(sources["tables"].keys())

    state = geography["state_fips"]
    crosswalk = load_crosswalk()   # {place_geoid: {county_geoid, overlap_share, name}}

    # Building Permits Survey data (from pipeline.fetch_bps), if present.
    permits_doc = {}
    pf = DATA / "permits.json"
    if pf.exists():
        permits_doc = json.loads(pf.read_text(encoding="utf-8")).get("areas", {})
        print(f"Loaded permits for {len(permits_doc)} areas from data/permits.json")
    else:
        print("No data/permits.json (run pipeline.fetch_bps) — permit_rate will be null")

    # NCES school data (from pipeline.fetch_schools), if present.
    schools_doc = {}
    schf = DATA / "schools.json"
    if schf.exists():
        schools_doc = json.loads(schf.read_text(encoding="utf-8"))
        print(f"Loaded schools for {len(schools_doc.get('counties', {}))} counties")
    else:
        print("No data/schools.json (run pipeline.fetch_schools) — school metrics will be null")
    schools_counties = schools_doc.get("counties", {})

    # HUD income limits / AMI (from pipeline.fetch_hud), if present.
    hud_doc = {}
    hudf = DATA / "hud.json"
    if hudf.exists():
        hud_doc = json.loads(hudf.read_text(encoding="utf-8"))
        print(f"Loaded HUD AMI for {len(hud_doc.get('counties', {}))} counties")
    else:
        print("No data/hud.json (run pipeline.fetch_hud) — income_vs_ami will be null")
    hud_counties = hud_doc.get("counties", {})

    client = CensusClient(acs["base_url"], acs["path"], acs["key_env"])

    print(f"Fetching ACS {year} (acs/acs5) for Utah: state, all counties, all places...")
    state_vars = fetch_level(client, year, tables, f"state:{state}")
    county_vars = fetch_level(client, year, tables, "county:*", f"state:{state}")
    place_vars = fetch_level(client, year, tables, "place:*", f"state:{state}")
    print(f"  counties: {len(county_vars)} | places: {len(place_vars)}")

    # Student yield per county: K-12 enrollment / occupied housing units.
    yield_by_county = {}
    for cc, vm in county_vars.items():
        occ = vm.get("B25002_002E")
        enr = schools_counties.get(cc, {}).get("total_enrollment")
        yield_by_county[cc] = (enr / occ) if (enr and occ) else None

    print(f"Fetching per-year time series {SERIES_YEARS}...")
    series = build_series(client, SERIES_YEARS, state)
    # population trend (int-year keys) derived from the series, for growth ratios
    trend = {gid: {int(y): snap["population"] for y, snap in yrs.items()}
             for gid, yrs in series.items()}
    # statewide 5-yr CAGR: projections fade each area's growth toward this long-run rate
    _st = trend.get(state, {})
    state_cagr = ((((_st.get(2024) or 0) / _st[2019]) ** (1 / 5) - 1)
                  if _st.get(2019) and _st.get(2024) else 0.013)

    # Assemble area records
    areas = []

    def county_of(geoid, level):
        if level == "county":
            return geoid
        if level == "place":
            return crosswalk.get(geoid, {}).get("county_geoid")
        return None

    def build_area(geoid, level, varmap):
        name = varmap.get("NAME", geoid)
        mm = compute_metrics(varmap, sources)
        derived = compute_derived(mm["metrics"], trend.get(geoid, {}))
        cc = county_of(geoid, level)
        perm = permits_doc.get(geoid, {})
        perm_years = sorted(int(y) for y in perm) if perm else []
        cur = perm.get(str(perm_years[-1])) if perm_years else None   # latest permit year
        pop = mm["metrics"].get("population")
        derived["permit_rate"] = (round(cur["total"] / pop * 1000, 3)
                                  if cur and pop else None)
        perm3 = (sum((perm.get(str(y)) or {}).get("total", 0) for y in perm_years[-3:])
                 if perm_years else None)
        sy = yield_by_county.get(cc)
        derived["student_yield"] = sy
        derived["projected_new_students"] = (round(perm3 * sy)
                                             if perm3 is not None and sy else None)
        ami = hud_counties.get(cc, {}).get("ami")
        mfi = mm["metrics"].get("median_family_income")
        derived["income_vs_ami"] = round(mfi / ami, 3) if (mfi and ami) else None
        # trend-based population projection (5-yr CAGR extrapolated, clamped)
        pt = trend.get(geoid, {})
        pop24 = mm["metrics"].get("population")
        pop19 = pt.get(2019)
        projection = None
        if pop24 and pop19 and pop19 > 0:
            area_cagr = max(-0.04, min(0.08, (pop24 / pop19) ** (1 / 5) - 1))
            k12_share = (mm["metrics"].get("pop_k12") or 0) / pop24

            def _p(yr, _a=area_cagr, _s=state_cagr, _b=pop24, _k=k12_share):
                # growth decays from the area's rate toward the state rate each year
                pop = _b
                for t in range(1, yr - 2024 + 1):
                    g = _s + (_a - _s) * (0.82 ** t)
                    pop *= (1 + g)
                p = round(pop)
                return {"pop": p, "net": p - _b, "growth_pct": round(p / _b - 1, 5),
                        "k12": round(p * _k)}

            projection = {"method": "trend: recent growth fading toward the Utah rate "
                                     "(damped 5-yr CAGR) — a scenario, not an official forecast",
                          "base_year": 2024, "base_pop": pop24,
                          "area_cagr": round(area_cagr, 5), "state_cagr": round(state_cagr, 5),
                          "y2030": _p(2030), "y2040": _p(2040)}
        rec = {
            "geoid": geoid,
            "level": level,
            "name": name,
            "vintage": year,
            "population": mm["metrics"].get("population"),
            "pop_trend": {str(y): trend.get(geoid, {}).get(y) for y in SERIES_YEARS},
            "series": series.get(geoid, {}),
            "permits": perm,
            "projection": projection,
            "metrics": mm["metrics"],
            "moe": mm["moe"],
            "derived": derived,
        }
        if level == "place":
            rec["county_geoid"] = cc
            rec["overlap_share"] = crosswalk.get(geoid, {}).get("overlap_share", 1.0)
        if level == "county":
            rec["schools"] = schools_counties.get(geoid)
            hc = hud_counties.get(geoid)
            if hc:
                rec["hud"] = {**hc, "year": hud_doc.get("year")}
        return rec, {**mm["metrics"], **derived}

    place_vals, county_vals = {}, {}
    for gid, vm in state_vars.items():
        rec, _ = build_area(gid, "state", vm)
        areas.append(rec)
    for gid, vm in sorted(county_vars.items()):
        rec, flat = build_area(gid, "county", vm)
        areas.append(rec)
        county_vals[gid] = flat
    for gid, vm in sorted(place_vars.items()):
        rec, flat = build_area(gid, "place", vm)
        areas.append(rec)
        place_vals[gid] = flat

    # Scores: places ranked among all Utah places; counties among all Utah counties.
    scored = {}
    scored.update(build_scores(place_vals, scores_cfg))
    scored.update(build_scores(county_vals, scores_cfg))

    built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta = {
        "built_at": built_at,
        "acs_dataset": "acs/acs5",
        "current_vintage": year,
        "trend_vintages": trend_vintages,
        "state": f"{geography['state_name']} ({state})",
        "focus_county": geography.get("county_geoid"),
        "peer_set": "all Utah places (cities) / all Utah counties",
        "n_places": len(place_vars),
        "n_counties": len(county_vars),
        "sources": [
            "U.S. Census Bureau, ACS 5-Year Detailed Tables",
            "U.S. Census Bureau, Building Permits Survey",
            "NCES Common Core of Data (Urban Institute Education Data API)",
            "HUD Income Limits",
        ],
        "notes": [
            "Population and 1/3/5-year change come from ACS B01003 across vintages.",
            "Phase 2: scores rank places among all Utah places and counties among all Utah counties.",
            "School + AMI figures are county/district-based; place->county via a point-in-polygon crosswalk.",
        ],
    }

    DATA.mkdir(exist_ok=True)
    (DATA / "areas.json").write_text(
        _compact({"meta": meta, "areas": areas}), encoding="utf-8")
    name_by_id = {a["geoid"]: a["name"] for a in areas}
    level_by_id = {a["geoid"]: a["level"] for a in areas}
    (DATA / "scores.json").write_text(_compact({
        "peer_set": meta["peer_set"],
        "vintage": year,
        "method": "average-rank percentile among same-level peers, 0-100",
        "areas": [
            {"geoid": g, "name": name_by_id.get(g), "level": level_by_id.get(g),
             "scores": scored[g]["scores"], "input_pct": scored[g]["input_pct"]}
            for g in sorted(scored)
        ],
    }), encoding="utf-8")
    (DATA / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # Score key for the in-app "Score key" view — single source of truth is scores.yaml.
    (DATA / "score_key.json").write_text(json.dumps({
        "derived_metrics": scores_cfg.get("derived_metrics", {}),
        "scores": {k: {"label": v.get("label", k),
                       "inputs": v.get("inputs", []),
                       "status": v.get("status")}
                   for k, v in scores_cfg["scores"].items()},
        "percentile_method": scores_cfg.get("percentile_method"),
    }, indent=2, default=str), encoding="utf-8")

    _print_verification(areas, scored)


def _pct(num, den):
    return f"{num / den * 100:.1f}%" if num is not None and den else "n/a"


def _print_verification(areas, scored):
    by_id = {a["geoid"]: a for a in areas}
    print("\n=== Verification: Davis County (49011) vs. source ===")
    c = by_id.get("49011")
    if c:
        m = c["metrics"]
        print(f"  Population (ACS 2024 B01003): {m['population']:,}")
        print(f"  Median HH income:            ${m['median_hh_income']:,}  (MOE +/- ${c['moe'].get('median_hh_income'):,})")
        print(f"  Median gross rent:           ${m['median_gross_rent']:,}")
        print(f"  Median home value:           ${m['median_home_value']:,}")
        print(f"  Owner share:                 {_pct(m['owner_occupied'], m['tenure_total'])}")
        print(f"  Vacancy rate:                {_pct(m['vacant_units'], m['housing_units'])}")
        print(f"  Pop trend: {c['pop_trend']}")
        print(f"  Growth 5y: {c['derived']['growth_5y']:.3%}  1y: {c['derived']['growth_1y']:.3%}")

    n_places = sum(1 for a in areas if a["level"] == "place")
    n_counties = sum(1 for a in areas if a["level"] == "county")
    print(f"\n=== Top Utah cities by population (of {n_places} places, {n_counties} counties) ===")
    print(f"  {'City':<18}{'Pop':>9}{'Demand':>9}{'Afford':>9}{'Supply':>9}{'Econ':>9}")
    places = sorted((a for a in areas if a["level"] == "place"),
                    key=lambda a: -(a["population"] or 0))
    for a in places[:12]:
        s = scored[a["geoid"]]["scores"]
        def f(x):
            return f"{x:>9.1f}" if x is not None else f"{'n/a':>9}"
        name = a["name"].replace(" city, Utah", "")
        print(f"  {name:<18}{(a['population'] or 0):>9,}"
              f"{f(s['demand'])}{f(s['affordability'])}{f(s['supply_tightness'])}{f(s['economic'])}")
    print("\nWrote data/areas.json, data/scores.json, data/meta.json")


if __name__ == "__main__":
    main()
