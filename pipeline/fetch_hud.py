"""Fetch HUD Income Limits (official Area Median Income + 30/50/80% limits).

Uses the HUD User API, which requires a free token in HUD_TOKEN (.env). HUD sets
income limits by metro/county; Davis County maps to the Ogden, UT MSA. The entity
id for a county is its 5-digit GEOID + "99999".

Writes data/hud.json: AMI and income limits (extremely-low 30%, very-low 50%,
low 80%) by household size 1-8.

Run from the repo root:
    .\\.venv\\Scripts\\python.exe -m pipeline.fetch_hud
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

import yaml

from pipeline.census_client import load_env

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
OUT = ROOT / "data" / "hud.json"

API = "https://www.huduser.gov/hudapi/public/il/data"
YEARS = [2026, 2025, 2024]       # try newest first


def _get(entity: str, year: int, token: str) -> dict:
    req = urllib.request.Request(f"{API}/{entity}?year={year}",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main() -> None:
    load_env()
    token = os.environ.get("HUD_TOKEN")
    if not token:
        raise SystemExit("HUD_TOKEN not set. Add it to .env (free token at "
                         "huduser.gov/portal/dataset/fmr-api.html).")

    geo = yaml.safe_load((CONFIG / "geography.yaml").read_text(encoding="utf-8"))
    entity = geo["county_geoid"] + "99999"

    data = None
    for year in YEARS:
        try:
            d = _get(entity, year, token).get("data")
            if d and d.get("median_income"):
                data = d
                break
        except Exception as e:  # pragma: no cover
            print(f"  year {year}: {e}")
    if not data:
        raise SystemExit("No HUD income-limits data returned for " + entity)

    def series(block: dict, pct: int) -> dict:
        return {str(n): block.get(f"il{pct}_p{n}") for n in range(1, 9)}

    out = {
        "source": f"HUD Income Limits FY{data['year']} (HUD User API)",
        "year": data["year"],
        "county_geoid": geo["county_geoid"],
        "area_name": data.get("area_name"),
        "ami": data.get("median_income"),           # Area Median (family) Income
        "limits": {
            "extremely_low_30": series(data["extremely_low"], 30),
            "very_low_50": series(data["very_low"], 50),
            "low_80": series(data["low"], 80),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote data/hud.json — {out['area_name']} FY{out['year']}: "
          f"AMI ${out['ami']:,}; limits 30/50/80% (4-person) "
          f"${out['limits']['extremely_low_30']['4']:,} / "
          f"${out['limits']['very_low_50']['4']:,} / "
          f"${out['limits']['low_80']['4']:,}")


if __name__ == "__main__":
    main()
