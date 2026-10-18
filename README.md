# Market Analysis Dashboard

Screens cities and counties for real estate and planning decisions. A Python pipeline
pulls public data (Census first) and writes JSON files; a static HTML page reads only
those files. See `SPEC.md` for the full build spec and `CLAUDE.md` for the working rules.

**Status: Phase 1 — Davis County, Utah.** Core Census pipeline proving the whole chain
on one county before widening to all of Utah (Phase 2) and the nation (Phase 3).

## Setup (Windows, PowerShell)

Python 3.12 is installed at `%LOCALAPPDATA%\Programs\Python\Python312`.

```powershell
# from the repo root
py -3.12 -m venv .venv            # or: & "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env       # then paste your CENSUS_API_KEY into .env
```

## Run the pipeline

```powershell
.\.venv\Scripts\python.exe -m pipeline.build
```

This fetches ACS 5-year data for Utah, Davis County, and the 15 Davis County cities,
computes derived ratios and composite scores, and writes:

- `data/areas.json`  — one record per area: raw metrics, margins of error, population trend
- `data/scores.json` — composite scores (0–100) for Davis County cities
- `data/meta.json`   — vintages, sources, build timestamp, and data notes

## What's verified against the live Census API (Oct 2026)

- ACS 5-year **vintage 2024** (2020–2024) is the current release.
- The Population Estimates (PEP) **API is unavailable for the 2020s** at county/place
  level, so population and its 1/3/5-year trend come from ACS B01003 across vintages.
- ACS null sentinels (negative "jam" values like `-666666666`) are converted to null.

Exact table/variable IDs live in `config/sources.yaml`.
