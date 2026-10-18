"""Fetch Davis County city boundaries as GeoJSON for the map layer.

Pulls generalized incorporated-place polygons (WGS84) from the Census TIGERweb
service and writes a single FeatureCollection to data/geo/davis_places.geojson.
Geometry rarely changes, so this is a separate, occasional step from build.py.

Run from the repo root:
    .\\.venv\\Scripts\\python.exe -m pipeline.fetch_geo
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
OUT = ROOT / "data" / "geo"

TIGERWEB = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
            "tigerWMS_Current/MapServer/28/query")  # layer 28 = Incorporated Places


def main() -> None:
    geography = yaml.safe_load((CONFIG / "geography.yaml").read_text(encoding="utf-8"))
    geoids = [p["geoid"] for p in geography["places"]]
    name_by_geoid = {p["geoid"]: p["name"] for p in geography["places"]}

    where = "GEOID IN (" + ",".join(f"'{g}'" for g in geoids) + ")"
    params = {
        "where": where,
        "outFields": "GEOID,NAME",
        "returnGeometry": "true",
        "geometryPrecision": "5",   # ~1 m; keeps the file small
        "outSR": "4326",
        "f": "geojson",
    }
    url = TIGERWEB + "?" + urllib.parse.urlencode(params)
    fc = json.load(urllib.request.urlopen(url, timeout=120))

    # Keep a tidy, stable set of properties (short name from our config).
    for feat in fc.get("features", []):
        gid = feat["properties"].get("GEOID")
        feat["properties"] = {"geoid": gid, "name": name_by_geoid.get(gid, feat["properties"].get("NAME"))}

    got = {f["properties"]["geoid"] for f in fc.get("features", [])}
    missing = [g for g in geoids if g not in got]
    if missing:
        print(f"WARNING: no geometry for {missing}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "davis_places.geojson").write_text(json.dumps(fc), encoding="utf-8")
    size = (OUT / "davis_places.geojson").stat().st_size
    print(f"Wrote data/geo/davis_places.geojson — {len(fc['features'])} features, {size:,} bytes")


if __name__ == "__main__":
    main()
