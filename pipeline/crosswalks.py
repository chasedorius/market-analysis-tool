"""Geography crosswalks.

Phase 1: the Davis County place list (with overlap shares) is curated in
config/geography.yaml. This module exposes it as a dict keyed by GEOID so the
build can filter the statewide ACS place pull down to Davis County.

Phase 2 replaces `davis_place_overlap()` with a crosswalk derived from an
authoritative Census relationship file, so cities crossing county lines get a
fractional overlap share. The rest of the pipeline won't change.
"""

from __future__ import annotations


def davis_place_overlap(geography: dict) -> dict[str, dict]:
    """Return {place_geoid: {name, overlap_share}} for Davis County cities."""
    return {
        p["geoid"]: {"name": p["name"], "overlap_share": p["overlap_share"]}
        for p in geography["places"]
    }
