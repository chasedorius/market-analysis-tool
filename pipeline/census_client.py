"""Thin Census API client.

- Reads the API key from the CENSUS_API_KEY environment variable (loaded from .env).
- Fetches one table at a time with get=group(TABLE), for a given geography.
- Converts ACS "jam" values (negative sentinels) to None.
- Returns, per geography row, a dict of {variable_id: value}.

The client never computes metrics; pipeline/transform.py does that. This keeps the
single place that touches the network small and easy to reason about.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Iterable

import requests

ROOT = Path(__file__).resolve().parent.parent

# Geography identifier columns are FIPS/GEOID strings and must keep their leading
# zeros (e.g. place "07690", county "011"). Never numeric-convert these.
GEO_COLUMNS = {
    "us", "region", "division", "state", "county", "place", "tract",
    "block group", "county subdivision", "zip code tabulation area",
    "congressional district", "school district (unified)",
    "school district (elementary)", "school district (secondary)",
    "metropolitan statistical area/micropolitan statistical area",
}


def load_env(env_path: Path | None = None) -> None:
    """Minimal .env loader (KEY=VALUE lines). Avoids an extra dependency."""
    env_path = env_path or (ROOT / ".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _to_number(raw: str):
    """Parse a Census value. Negative sentinels -> None; '' and '.' -> None.

    No legitimate ACS count or dollar estimate is negative, so any negative value
    is one of the jam sentinels (-666666666, -888888888, -999999999, ...).
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if s in ("", ".", "N", "null", "-"):
        return None
    try:
        val = float(s)
    except ValueError:
        return s  # keep non-numeric (e.g. NAME) as-is
    if val < 0:
        return None
    # return int when it is a whole number (counts), else float (ratios never come
    # straight from the API, so this is just medians, which are whole dollars)
    return int(val) if val.is_integer() else val


class CensusClient:
    def __init__(self, base_url: str, path: str, key_env: str = "CENSUS_API_KEY",
                 max_retries: int = 3, pause: float = 0.3):
        self.base_url = base_url.rstrip("/")
        self.path = path.strip("/")
        self.key = os.environ.get(key_env)
        if not self.key:
            raise RuntimeError(
                f"{key_env} is not set. Copy .env.example to .env and add your key."
            )
        self.max_retries = max_retries
        self.pause = pause
        self.session = requests.Session()

    def fetch_group(self, year: int, group: str, for_geo: str,
                    in_geo: str | None = None) -> list[dict]:
        """Fetch one table group for a geography. Returns a list of row dicts
        keyed by variable id (plus NAME, state, county/place)."""
        url = f"{self.base_url}/{year}/{self.path}"
        params = {"get": f"group({group})", "for": for_geo, "key": self.key}
        if in_geo:
            params["in"] = in_geo
        data = self._get(url, params)
        header, *rows = data
        out = []
        for row in rows:
            out.append({
                col: (val if col in GEO_COLUMNS else _to_number(val))
                for col, val in zip(header, row)
            })
        time.sleep(self.pause)  # be polite to the API
        return out

    def _get(self, url: str, params: dict):
        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=60)
                if resp.status_code == 200:
                    return resp.json()
                last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except requests.RequestException as exc:  # pragma: no cover
                last_err = str(exc)
            time.sleep(self.pause * attempt * 2)
        raise RuntimeError(f"Census request failed after {self.max_retries} tries: "
                           f"{url} {params.get('for')} -> {last_err}")


def geoid_of(row: dict) -> str:
    """Build the GEOID from a row's geography components."""
    if "place" in row:
        return f"{row['state']}{row['place']}"
    if "county" in row:
        return f"{row['state']}{row['county']}"
    return str(row["state"])
