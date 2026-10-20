"""Place -> county crosswalk.

Built by pipeline.fetch_geo via point-in-polygon of each place's internal point
against county polygons, stored in data/crosswalk_place_county.json as
{place_geoid: {name, county_geoid, overlap_share}}.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_crosswalk() -> dict:
    p = ROOT / "data" / "crosswalk_place_county.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
