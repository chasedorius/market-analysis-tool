"""Fetch NCES Common Core of Data (CCD) school data for all Utah counties.

Uses the Urban Institute Education Data API (free, no key), which wraps NCES CCD.
Schools are district-based and do not nest in cities, so school figures are
reported at the COUNTY level (per SPEC.md): total enrollment, charter share,
school counts, a multi-year enrollment trend, and geocoded school locations.

Writes data/schools.json keyed by county GEOID.

Run from the repo root:
    .\\.venv\\Scripts\\python.exe -m pipeline.fetch_schools
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "schools.json"

API = "https://educationdata.urban.org/api/v1"
CURRENT_YEAR = 2023
TREND_YEARS = [2019, 2020, 2021, 2022, 2023]


def _fetch(url: str, tries: int = 4) -> dict:
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                return json.load(r)
        except Exception as e:  # transient timeouts happen on the big UT directory
            last = e
            time.sleep(2 * (i + 1))
    raise last


def _get_all(url: str) -> list:
    out, pages = [], 0
    while url and pages < 40:
        d = _fetch(url)
        out += d["results"]
        url = d.get("next")
        pages += 1
    return out


def main() -> None:
    counties: dict[str, dict] = {}
    for year in TREND_YEARS:
        rows = _get_all(f"{API}/schools/ccd/directory/{year}/?fips=49")
        for x in rows:
            cc = str(x.get("county_code"))
            if len(cc) != 5 or not cc.startswith("49"):
                continue
            e = x["enrollment"] if (x.get("enrollment") or 0) > 0 else 0
            c = counties.setdefault(cc, {"trend": {}, "locations": [],
                                         "total": 0, "charter_enr": 0,
                                         "n": 0, "n_charter": 0})
            c["trend"][str(year)] = c["trend"].get(str(year), 0) + e
            if year == CURRENT_YEAR:
                c["total"] += e
                c["n"] += 1
                if x.get("charter") == 1:
                    c["charter_enr"] += e
                    c["n_charter"] += 1
                if x.get("latitude") and x.get("longitude"):
                    c["locations"].append({
                        "name": x["school_name"], "lat": x["latitude"],
                        "lon": x["longitude"], "charter": x.get("charter") == 1,
                        "enrollment": e or None})
        print(f"  {year}: directory parsed")

    out_counties = {}
    for cc, c in counties.items():
        out_counties[cc] = {
            "total_enrollment": c["total"],
            "charter_enrollment": c["charter_enr"],
            "charter_share": (c["charter_enr"] / c["total"]) if c["total"] else None,
            "n_schools": c["n"],
            "n_charter": c["n_charter"],
            "enrollment_trend": c["trend"],
            "locations": c["locations"],
        }

    out = {
        "source": "NCES Common Core of Data via Urban Institute Education Data API",
        "year": CURRENT_YEAR,
        "counties": out_counties,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out), encoding="utf-8")
    tot = sum(c["total_enrollment"] for c in out_counties.values())
    print(f"Wrote data/schools.json — {len(out_counties)} counties, "
          f"{tot:,} students, {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
