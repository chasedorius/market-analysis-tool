"""Phase 2 geography: Utah county + place boundaries and a place->county crosswalk.

Fetches generalized polygons from Census TIGERweb and assigns each place to its
county by point-in-polygon on the place's internal point (no GIS dependency).
Writes:
  data/geo/ut_counties.geojson   - 29 county polygons (state choropleth)
  data/geo/ut_places.geojson     - all places, county_geoid baked into properties
  data/crosswalk_place_county.json

Run from the repo root:
    .\\.venv\\Scripts\\python.exe -m pipeline.fetch_geo
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "data" / "geo"
TIGER = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
         "tigerWMS_Current/MapServer")
STATE = "49"
PLACE_LAYERS = [28, 30]   # 28 = Incorporated Places, 30 = Census Designated Places


def _query(layer: int, geom: bool) -> dict:
    params = {
        "where": f"STATE='{STATE}'",
        "outFields": "GEOID,NAME,INTPTLAT,INTPTLON",
        "returnGeometry": "true" if geom else "false",
        "outSR": "4326",
        "f": "geojson" if geom else "json",
    }
    if geom:
        params["geometryPrecision"] = "4"
        params["maxAllowableOffset"] = "0.0015"   # ~150 m generalization, small files
    url = f"{TIGER}/{layer}/query?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=180) as r:
        return json.load(r)


def _rings(geom: dict):
    """Exterior rings only (holes ignored; Utah counties have none that matter)."""
    if geom["type"] == "Polygon":
        yield geom["coordinates"][0]
    elif geom["type"] == "MultiPolygon":
        for poly in geom["coordinates"]:
            yield poly[0]


def _inside(lon: float, lat: float, rings: list) -> bool:
    """Ray-casting point-in-polygon across all (disjoint) exterior rings."""
    inside = False
    for ring in rings:
        n = len(ring)
        j = n - 1
        for i in range(n):
            xi, yi = ring[i][0], ring[i][1]
            xj, yj = ring[j][0], ring[j][1]
            if ((yi > lat) != (yj > lat)) and \
               (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
    return inside


def main() -> None:
    GEO.mkdir(parents=True, exist_ok=True)

    counties = _query(82, geom=True)
    county_rings = {f["properties"]["GEOID"]: list(_rings(f["geometry"]))
                    for f in counties["features"]}
    print(f"counties: {len(county_rings)}")

    # place internal points (for the crosswalk)
    pts = []
    for layer in PLACE_LAYERS:
        for feat in _query(layer, geom=False)["features"]:
            a = feat["attributes"]
            pts.append({"geoid": a["GEOID"], "name": a["NAME"],
                        "lat": float(a["INTPTLAT"]), "lon": float(a["INTPTLON"])})

    xwalk = {}
    for p in pts:
        county = next((gid for gid, rings in county_rings.items()
                       if _inside(p["lon"], p["lat"], rings)), None)
        xwalk[p["geoid"]] = {"name": p["name"], "county_geoid": county,
                             "overlap_share": 1.0}
    unassigned = [g for g, v in xwalk.items() if not v["county_geoid"]]
    print(f"places: {len(pts)} | assigned: {len(pts) - len(unassigned)} | "
          f"unassigned: {unassigned}")

    # county geojson (trim props)
    for f in counties["features"]:
        f["properties"] = {"geoid": f["properties"]["GEOID"],
                           "name": f["properties"]["NAME"]}
    (GEO / "ut_counties.geojson").write_text(json.dumps(counties), encoding="utf-8")

    # place geojson with county baked in
    feats = []
    for layer in PLACE_LAYERS:
        for feat in _query(layer, geom=True)["features"]:
            gid = feat["properties"]["GEOID"]
            feat["properties"] = {"geoid": gid, "name": feat["properties"]["NAME"],
                                  "county_geoid": xwalk.get(gid, {}).get("county_geoid")}
            feats.append(feat)
    (GEO / "ut_places.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")

    (ROOT / "data" / "crosswalk_place_county.json").write_text(
        json.dumps(xwalk, indent=2), encoding="utf-8")

    print(f"Wrote ut_counties.geojson ({(GEO/'ut_counties.geojson').stat().st_size:,} b), "
          f"ut_places.geojson ({(GEO/'ut_places.geojson').stat().st_size:,} b), "
          f"crosswalk_place_county.json")


if __name__ == "__main__":
    main()
