"""Fetch Census Building Permits Survey (BPS) data for Davis County + its cities.

BPS is flat files (not the ACS API):
  County:  https://www2.census.gov/econ/bps/County/co{YEAR}a.txt   (national)
  Place:   https://www2.census.gov/econ/bps/Place/West Region/we{YEAR}a.txt

Both have two header rows then comma-separated data. Column layout verified
2026-10-17. We keep permitted UNITS by structure type (single-family, 2-4, 5+).
Writes data/permits.json keyed on GEOID + year.

Run from the repo root:
    .\\.venv\\Scripts\\python.exe -m pipeline.fetch_bps
"""

from __future__ import annotations

import csv
import io
import json
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
OUT = ROOT / "data" / "permits.json"

YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]  # latest full-year BPS annual
BASE = "https://www2.census.gov/econ/bps"

# 0-based column indices for UNITS by structure type (verified against the files).
COUNTY_COLS = {"state": 1, "county": 2, "sf": 7, "u2": 10, "u34": 13, "mf": 16}
PLACE_COLS = {"state": 1, "county": 3, "fips_place": 5, "sf": 18, "u2": 21, "u34": 24, "mf": 27}


def _rows(url: str):
    with urllib.request.urlopen(url, timeout=120) as resp:
        text = resp.read().decode("latin-1")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    return rows[3:]  # skip 2 header rows + 1 blank


def _int(x):
    x = (x or "").strip()
    return int(x) if x.lstrip("-").isdigit() else 0


def _point(r, c):
    sf = _int(r[c["sf"]])
    u2_4 = _int(r[c["u2"]]) + _int(r[c["u34"]])
    mf = _int(r[c["mf"]])
    return {"single_family": sf, "units_2_4": u2_4, "multifamily_5plus": mf,
            "total": sf + u2_4 + mf}


def main() -> None:
    geo = yaml.safe_load((CONFIG / "geography.yaml").read_text(encoding="utf-8"))
    state = geo["state_fips"]

    out: dict[str, dict] = {}

    for year in YEARS:
        # --- all Utah counties ---
        for r in _rows(f"{BASE}/County/co{year}a.txt"):
            c = COUNTY_COLS
            if len(r) <= c["mf"] or r[c["state"]].strip() != state:
                continue
            out.setdefault(state + r[c["county"]].strip(), {})[str(year)] = _point(r, c)

        # --- all Utah places (West region file) ---
        url = f"{BASE}/Place/{urllib.parse.quote('West Region')}/we{year}a.txt"
        for r in _rows(url):
            c = PLACE_COLS
            if len(r) <= c["mf"] or r[c["state"]].strip() != state:
                continue
            fips = r[c["fips_place"]].strip()
            if fips == "99990":       # county unincorporated remainder
                continue
            out.setdefault(state + fips, {})[str(year)] = _point(r, c)
        print(f"  {year}: parsed Utah counties + places")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": "U.S. Census Bureau, Building Permits Survey (annual)",
        "years": YEARS,
        "note": "Permitted housing units by structure type. 5+ unit = multifamily.",
        "areas": out,
    }, indent=2), encoding="utf-8")
    n = len(out)
    print(f"Wrote data/permits.json — {n} areas, years {YEARS[0]}–{YEARS[-1]} "
          f"({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
