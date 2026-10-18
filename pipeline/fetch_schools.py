"""Fetch NCES Common Core of Data (CCD) school data for Davis County.

Uses the Urban Institute Education Data API (free, no key), which wraps NCES CCD.
Schools are district-based and do not nest in cities, so school figures are
reported at the Davis County / Davis School District level (per SPEC.md).

Writes data/schools.json:
  - county enrollment, charter share, school + charter counts
  - enrollment by grade (Davis School District)
  - multi-year district enrollment trend
  - school locations (name, lat/lon, charter, enrollment) for the map

Run from the repo root:
    .\\.venv\\Scripts\\python.exe -m pipeline.fetch_schools
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
OUT = ROOT / "data" / "schools.json"

API = "https://educationdata.urban.org/api/v1"
YEAR = 2023                      # latest finalized CCD vintage with enrollment
TREND_YEARS = [2019, 2020, 2021, 2022, 2023]
DAVIS_DISTRICT = "4900210"       # Davis School District (NCES LEAID)


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=90) as r:
        return json.load(r)


def _get_all(url: str) -> list:
    out, pages = [], 0
    while url and pages < 30:
        d = _get(url)
        out += d["results"]
        url = d.get("next")
        pages += 1
    return out


def _district_total(year: int, slug: str) -> int:
    """Aggregate (race=99, sex=99) enrollment for a grade slug, dropping sentinels."""
    d = _get(f"{API}/school-districts/ccd/enrollment/{year}/{slug}/?leaid={DAVIS_DISTRICT}")
    rows = [r for r in d["results"] if r.get("race") == 99 and r.get("sex") == 99]
    return sum(r["enrollment"] for r in rows if (r.get("enrollment") or 0) > 0)


def main() -> None:
    geo = yaml.safe_load((CONFIG / "geography.yaml").read_text(encoding="utf-8"))
    county = geo["county_fips"]

    # Schools physically in Davis County (county_code filter is client-side; the
    # API's county_code query param is ignored, so we fetch Utah and filter).
    allut = _get_all(f"{API}/schools/ccd/directory/{YEAR}/?fips=49")
    schools = [x for x in allut if str(x.get("county_code")) == f"49{county}"]

    def enr(x):
        return x["enrollment"] if (x.get("enrollment") or 0) > 0 else 0

    total = sum(enr(x) for x in schools)
    charter_enr = sum(enr(x) for x in schools if x.get("charter") == 1)
    locations = [{
        "name": x["school_name"], "lat": x["latitude"], "lon": x["longitude"],
        "charter": x.get("charter") == 1, "enrollment": enr(x) or None,
        "low": x.get("lowest_grade_offered"), "high": x.get("highest_grade_offered"),
    } for x in schools if x.get("latitude") and x.get("longitude")]

    grade_slugs = [("grade-pk", "PK"), ("grade-k", "K")] + \
                  [(f"grade-{n}", str(n)) for n in range(1, 13)]
    by_grade = []
    for slug, label in grade_slugs:
        try:
            by_grade.append({"grade": label, "enrollment": _district_total(YEAR, slug)})
        except Exception as e:  # pragma: no cover
            print(f"  skip {slug}: {e}")

    trend = {}
    for y in TREND_YEARS:
        try:
            trend[str(y)] = _district_total(y, "grade-99")
        except Exception as e:  # pragma: no cover
            print(f"  skip trend {y}: {e}")

    out = {
        "source": "NCES Common Core of Data via Urban Institute Education Data API",
        "year": YEAR,
        "county_geoid": geo["county_geoid"],
        "district": {"leaid": DAVIS_DISTRICT, "name": "Davis School District"},
        "county_total_enrollment": total,
        "charter_enrollment": charter_enr,
        "charter_share": (charter_enr / total) if total else None,
        "n_schools": len(schools),
        "n_charter": sum(1 for x in schools if x.get("charter") == 1),
        "enrollment_by_grade": by_grade,
        "enrollment_trend": trend,
        "locations": locations,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote data/schools.json — {len(schools)} schools, enrollment {total:,}, "
          f"charter {out['charter_share']*100:.1f}%, {len(by_grade)} grades, "
          f"{len(trend)} trend years ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
