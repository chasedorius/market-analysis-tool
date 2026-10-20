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
from pipeline.crosswalks import davis_place_overlap
from pipeline.scores import build_scores
from pipeline.transform import compute_derived, compute_metrics

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"


def load_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG / name).read_text(encoding="utf-8"))


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


def build_series(client, years, state, county, davis_ids) -> dict[str, dict]:
    """{geoid: {year: snapshot}} for state, county, and Davis County places."""
    out: dict[str, dict] = {}
    levels = [(f"state:{state}", None),
              (f"county:{county}", f"state:{state}"),
              ("place:*", f"state:{state}")]
    for year in years:
        for for_geo, in_geo in levels:
            vmap = fetch_level(client, year, SERIES_TABLES, for_geo, in_geo)
            for gid, vm in vmap.items():
                if for_geo == "place:*" and gid not in davis_ids:
                    continue
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
    county = geography["county_fips"]
    davis_places = davis_place_overlap(geography)

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
        print(f"Loaded schools (enrollment {schools_doc.get('county_total_enrollment'):,})")
    else:
        print("No data/schools.json (run pipeline.fetch_schools) — school metrics will be null")

    # HUD income limits / AMI (from pipeline.fetch_hud), if present.
    hud_doc = {}
    hudf = DATA / "hud.json"
    if hudf.exists():
        hud_doc = json.loads(hudf.read_text(encoding="utf-8"))
        print(f"Loaded HUD AMI ${hud_doc.get('ami'):,} ({hud_doc.get('area_name')})")
    else:
        print("No data/hud.json (run pipeline.fetch_hud) — income_vs_ami will be null")

    client = CensusClient(acs["base_url"], acs["path"], acs["key_env"])

    print(f"Fetching ACS {year} (acs/acs5) for Utah, Davis County, and places...")
    state_vars = fetch_level(client, year, tables, f"state:{state}")
    county_vars = fetch_level(client, year, tables, f"county:{county}", f"state:{state}")
    place_vars_all = fetch_level(client, year, tables, "place:*", f"state:{state}")
    place_vars = {gid: v for gid, v in place_vars_all.items() if gid in davis_places}
    print(f"  places in Utah: {len(place_vars_all)}; kept in Davis County: {len(place_vars)}")

    # Student yield (county-level): K-12 enrollment per occupied housing unit.
    county_occ = county_vars.get(geography["county_geoid"], {}).get("B25002_002E")
    school_total = schools_doc.get("county_total_enrollment")
    student_yield = (school_total / county_occ) if (school_total and county_occ) else None

    print(f"Fetching per-year time series {SERIES_YEARS}...")
    series = build_series(client, SERIES_YEARS, state, county, set(davis_places))
    # population trend (int-year keys) derived from the series, for growth ratios
    trend = {gid: {int(y): snap["population"] for y, snap in yrs.items()}
             for gid, yrs in series.items()}

    # Assemble area records
    areas = []
    area_values_for_scoring: dict[str, dict] = {}

    def build_area(geoid, level, varmap):
        name = varmap.get("NAME", geoid)
        mm = compute_metrics(varmap, sources)
        derived = compute_derived(mm["metrics"], trend.get(geoid, {}))
        perm = permits_doc.get(geoid, {})
        cur = perm.get(str(year))
        pop = mm["metrics"].get("population")
        derived["permit_rate"] = (round(cur["total"] / pop * 1000, 3)
                                  if cur and pop else None)
        perm3 = (sum((perm.get(str(y)) or {}).get("total", 0) for y in (2022, 2023, 2024))
                 if perm else None)
        derived["student_yield"] = student_yield
        derived["projected_new_students"] = (round(perm3 * student_yield)
                                             if perm3 is not None and student_yield else None)
        ami = hud_doc.get("ami")
        mfi = mm["metrics"].get("median_family_income")
        derived["income_vs_ami"] = round(mfi / ami, 3) if (mfi and ami) else None
        rec = {
            "geoid": geoid,
            "level": level,
            "name": name,
            "vintage": year,
            "population": mm["metrics"].get("population"),
            "pop_trend": {str(y): trend.get(geoid, {}).get(y) for y in SERIES_YEARS},
            "series": series.get(geoid, {}),
            "permits": perm,
            "metrics": mm["metrics"],
            "moe": mm["moe"],
            "derived": derived,
        }
        if level == "place":
            rec["overlap_share"] = davis_places[geoid]["overlap_share"]
        if level == "county":
            rec["schools"] = schools_doc
            rec["hud"] = hud_doc
        return rec, {**mm["metrics"], **derived}

    for gid, vm in state_vars.items():
        rec, _ = build_area(gid, "state", vm)
        areas.append(rec)
    for gid, vm in county_vars.items():
        rec, _ = build_area(gid, "county", vm)
        areas.append(rec)
    for gid, vm in sorted(place_vars.items()):
        rec, flat = build_area(gid, "place", vm)
        areas.append(rec)
        area_values_for_scoring[gid] = flat  # peer set = Davis County cities

    scored = build_scores(area_values_for_scoring, scores_cfg)

    built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta = {
        "built_at": built_at,
        "acs_dataset": "acs/acs5",
        "current_vintage": year,
        "trend_vintages": trend_vintages,
        "county": f"{geography['county_name']}, {geography['state_name']} ({geography['county_geoid']})",
        "peer_set": "Davis County cities (15)",
        "n_places": len(place_vars),
        "sources": ["U.S. Census Bureau, ACS 5-Year Detailed Tables"],
        "notes": [
            "Population and 1/3/5-year change come from ACS B01003 across vintages "
            "(5-year period estimates); the PEP API is unavailable for the 2020s.",
            "Phase 1 scores rank Davis County cities against each other; all-Utah "
            "ranking arrives in Phase 2.",
            "School demand score and the schools/industrial/retail modules await "
            "non-Census sources (NCES, BLS, HUD, Building Permits).",
        ],
    }

    DATA.mkdir(exist_ok=True)
    (DATA / "areas.json").write_text(
        json.dumps({"meta": meta, "areas": areas}, indent=2), encoding="utf-8")
    (DATA / "scores.json").write_text(json.dumps({
        "peer_set": meta["peer_set"],
        "vintage": year,
        "method": "average-rank percentile among peers, 0-100",
        "areas": [
            {"geoid": g, "name": next(a["name"] for a in areas if a["geoid"] == g),
             "scores": scored[g]["scores"], "input_pct": scored[g]["input_pct"]}
            for g in sorted(scored)
        ],
    }, indent=2), encoding="utf-8")
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

    print("\n=== Davis County cities: population + scores ===")
    print(f"  {'City':<18}{'Pop':>9}{'Demand':>9}{'Afford':>9}{'Supply':>9}{'Econ':>9}")
    places = sorted((a for a in areas if a["level"] == "place"),
                    key=lambda a: -(a["population"] or 0))
    for a in places:
        s = scored[a["geoid"]]["scores"]
        def f(x):
            return f"{x:>9.1f}" if x is not None else f"{'n/a':>9}"
        name = a["name"].replace(" city, Utah", "")
        print(f"  {name:<18}{(a['population'] or 0):>9,}"
              f"{f(s['demand'])}{f(s['affordability'])}{f(s['supply_tightness'])}{f(s['economic'])}")
    print("\nWrote data/areas.json, data/scores.json, data/meta.json")


if __name__ == "__main__":
    main()
