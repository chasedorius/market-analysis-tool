# Market Analysis Dashboard

Purpose: screen cities and counties for real estate and planning decisions. A core metric set plus use-case modules (land acquisition, multifamily, townhomes and residential, schools, industrial, retail, custom). Utah-first, nationwide-capable.

## Rules
- Key all data on Census GEOID plus vintage year.
- Roll up from counts and recompute ratios. Never average percentages.
- Store the ACS margin of error with every estimate; flag unreliable small places.
- Pipeline (Python, /pipeline) writes JSON to /data. The front end (/web) is a static HTML page that reads only /data. Never call data APIs from the browser.
- CENSUS_API_KEY comes from an environment variable. Never commit it.
- Score and ratio formulas live in config/scores.yaml and must match the in-app score key.
- Crosswalks (place to county, school district to place) store overlap shares.
- Use cases are modules defined in config/modules.yaml. Core views never depend on a module.

## Build order
Phase 1 Davis County, Phase 2 Utah, Phase 3 national, Phase 4 tracts and ZIP.
Do not start a phase until the previous phase's done-when checks pass.

Full spec: SPEC.md
