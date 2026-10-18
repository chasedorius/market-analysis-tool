# Market Analysis Dashboard: Build Spec

Oct 16, 2026

## Purpose and users

This tool screens cities and counties for any real estate or planning decision that depends on local demographics and market fundamentals. A core set of metrics applies to every use case, and use-case modules (land acquisition, multifamily, schools and others you add) reuse the same data. It is built Utah-first, with data structures that work for every state from day one.

The main user is the owner, with occasional view-only access for partners and lenders. The core questions every use case shares:

- Is demand growing? Population trend and projections.
- Is housing being built? Permits and new units per capita.
- Who lives there? Household income, owner vs. renter share.
- Is it affordable? Area median income (AMI), rent-to-income.
- Are there jobs? Employment, wages, unemployment.
- Who is coming? Births, age mix and in-migration.

Use cases sit on top of that core as modules. A module is a saved set of metrics, scores and buy-box presets, so adding one does not change the data pipeline.

| Module | Decision it supports | Leans on |
| --- | --- | --- |
| Land acquisition | Where to buy land and build | Growth, permits, income vs. AMI, rent-to-income |
| Multifamily and rentals | Where rental demand outruns supply | Renter share, rent growth, vacancy, permits for 5+ units |
| Townhomes and residential | Where for-sale housing has demand | Home value, price-to-income, owner share, attached-home share, household growth |
| Schools | Whether an area has enough students | Enrollment, charter share, births, under-5 pipeline |
| Industrial | Where warehouse, logistics or flex demand is building | Industrial jobs and wages, labor force, commuting flows |
| Retail | Where population and income support new retail space | Household growth and income, retail jobs and establishments |
| Underwriting context | Market support for a deal or lender package | Population, employment, rent and vacancy trends |
| Custom | Anything else | Any metrics and weights you choose |

Not in v1: parcel-level data, user logins, paid data feeds, school attendance-boundary maps.

## Geography model

Every record is keyed on Census GEOID plus a data vintage year, so areas roll up cleanly and every state works the same way. City and county are the primary levels; the rest are added in later phases.

| Level | Key | Role | Phase |
| --- | --- | --- | --- |
| State | 2-digit FIPS | Peer group for scores | 1 |
| County | 5-digit FIPS (state + county) | Primary level | 1 |
| Place (city) | 7-digit GEOID (state + place) | Primary level; includes census-designated places | 1 |
| School district | NCES district ID | School demand; does not nest in cities or counties | 2 |
| ZIP (ZCTA) | 5-digit | Lookup convenience only | 3 |
| Census tract | 11-digit GEOID | Map layer inside a county | 4 |

Rules the build must follow:

- Roll up from counts (tract to county to state) and recompute ratios from the summed counts. Never average percentages.
- Cities can span counties, and school districts overlap cities. Store crosswalk tables with an overlap share instead of forcing a single parent.
- Keep the vintage year on every row so boundary changes between years are visible.

## Metrics and data sources

Each metric answers one of the screening questions. National sources load for all states; Utah sources are added as a deeper layer.

| Question | Metric | Source | Lowest geography | Refresh |
| --- | --- | --- | --- | --- |
| Is demand growing? | Population, with 1-, 3- and 5-year change | Census Population Estimates; ACS | Place | Annual |
| Is demand growing? | Population projections | Gardner Policy Institute (Utah only) | County | Irregular |
| Is housing being built? | Permits by structure type (1 unit, 2-4, 5+) | Census Building Permits Survey | Place, county | Monthly, rolled up annually |
| Who lives there? | Median household income, owner vs. renter share, median rent, home value, vacancy | ACS 5-year | Place | Annual |
| Is it affordable? | AMI and income limits | HUD income limits | County, metro area | Annual |
| Are there jobs? | Employment, wages, unemployment | BLS (LAUS, QCEW); Utah Department of Workforce Services | County | Monthly, quarterly |
| Is there school demand? | Enrollment by grade, charter enrollment and school locations | NCES Common Core of Data; Utah State Board of Education | District, school | Annual |
| Is the school pipeline growing? | Births; population under 5 | State vital statistics or CDC natality files; ACS | County (births), place (under 5) | Annual |

Data notes:

- Use ACS 5-year for cities. The 1-year release only covers areas of roughly 65,000 people or more.
- Store the margin of error for every ACS value and flag low-reliability small places in the interface.
- Source names and coverage above come from general knowledge. Confirm table IDs, endpoints and release timing in Phase 1 before building on them.

Two sites to use alongside the pipeline:

- [data.census.gov](https://data.census.gov/) is the place to look up table IDs and spot-check values against the source. The pipeline itself pulls from the Census API, not the website.
- [Gardner Institute demographics](https://gardner.utah.edu/demographics/) supplies Utah population estimates and projections, plus in-migration by origin, fertility rates and temporary-resident estimates for areas such as Washington County.

The townhome, industrial and retail modules need data beyond the core set:

| Module | Added data | Source | Gap |
| --- | --- | --- | --- |
| Townhomes and residential | Attached-home share; permits by structure type | ACS (units in structure); Census Building Permits Survey | Permits are reported by unit count, so townhomes are not broken out |
| Industrial | Jobs and establishments by industry; wages; where workers live and commute | Census County Business Patterns; BLS QCEW; Census LEHD/LODES | Rent, vacancy and absorption are not in Census data |
| Retail | Retail jobs and establishments; household income and growth | County Business Patterns; QCEW; ACS | Rent, vacancy and traffic counts are not in Census data |

For industrial and retail, Census data shows the demand drivers (people, jobs, income) but not rents, vacancy or inventory. The pipeline reserves a slot to import those from a broker report or data subscription as CSV files.

## Derived scores and screener

Raw metrics feed a few derived ratios, which roll into five composite scores per area. Every formula lives in one config file and is shown in the app, so nothing on screen is a black box.

| Derived metric | Definition |
| --- | --- |
| Growth rate (n years) | (population now − population n years ago) ÷ population n years ago |
| Permit rate | Permitted units per year ÷ population × 1,000 |
| Rent-to-income | Median gross rent × 12 ÷ median household income |
| Price-to-income | Median home value ÷ median household income |
| Charter share | Charter enrollment ÷ (charter + district enrollment) in the area |
| Pipeline ratio | Children under 5 ÷ children 5-9. Above 1 means the pipeline is growing |
| Student yield | K-12 enrollment ÷ occupied housing units |
| Projected new students | Units permitted over the next 3 years × student yield |

Composite scores run 0 to 100. Each is the average percentile rank of its inputs among areas in the same state:

```latex
S_a = \frac{1}{n_a} \sum_{i \in a} \operatorname{pctrank}_{\text{state}}(x_i)
```

| Score | Inputs |
| --- | --- |
| Demand | 5-year growth, 1-year growth, pipeline ratio |
| Affordability | Rent-to-income, price-to-income, income vs. AMI (inverted so higher is more affordable) |
| Supply tightness | Vacancy (inverted), permit rate (inverted) |
| Economic | Median household income, unemployment (inverted), employment growth |
| School demand | Enrollment trend, pipeline ratio, projected new students |

The first four scores apply to every use case. School demand shows only when the schools module is on, and custom modules can add scores of their own.

The screener ranks every city or county against a saved buy box. A buy box is a set of minimum and maximum limits on any metric or score, for example a floor on 5-year growth and a ceiling on rent-to-income. Each module ships its own presets, and a custom buy box can mix metrics from any module. Results show as a ranked table with each score, and export to CSV. Your actual thresholds go in as presets once you set them.

## Dashboard views

The layout follows the [reference dashboard video](https://www.youtube.com/watch?v=gGj1VJ6fmy4) (map on the left, detail panels on the right and below), extended with schools and the screener. The front end is a single static HTML page.

| View | What it shows | Origin |
| --- | --- | --- |
| Map | State to county or city drill-down, colored by the selected metric; metric buttons for population growth, income, rent, home value, unemployment, vacancy, renters and school metrics; 1Y / 3Y / 5Y toggle | Reference |
| Delta cards | 1-, 3- and 5-year change for the selected area | Reference |
| Profile vs. state | Radar of the five composite scores against the state average | Reference, with a school axis added |
| Trends | Scores and ratios over time, with a zoomed y-axis so small changes are visible | Reference, axis fixed |
| Housing stock | Structure type, owner/renter split, pre-1980 share, overcrowding | Reference |
| Permits and new homes | Single-family and multifamily permits, year over year | Reference, covering Utah first |
| Affordability | AMI and income limits, affordability gap, income distribution | Reference, HUD data added |
| Schools | Enrollment by grade over time, charter share and locations, births and under-5 pipeline, projected new students | New |
| Screener | Side panel with buy-box filters, ranked results, presets, CSV export | Reference, expanded |
| Score key | In-app definition of every score and formula | New |
| Map settings and tract layer | Opacity, borders, tract toggle | Reference, Phase 4 |

Core views (map, delta cards, profile vs. state, trends, housing stock, permits, affordability, screener, score key) always show. The Schools view appears when that module is on, and new modules plug in without changing the core.

## Architecture and data pipeline

A Python pipeline pulls public data and writes JSON files; a static HTML page reads only those files. Nothing in the browser calls Census, BLS or any other API.

Data flows one way:

1. **Public sources:** Census Bureau API, BLS and HUD, NCES school data, Utah state sources.
2. **Python pipeline:** fetches and cleans, builds crosswalks, computes scores, holds the API key. Reads score definitions from `scores.yaml`.
3. **JSON data files:** keyed on GEOID plus vintage year, stored in the repo, rebuilt on each refresh.
4. **Static HTML page:** maps and charts, screener and score key. Reads `/data` only, makes no API calls.
5. **Hosted link:** view-only access.

The pipeline is the only part that touches an API key; scores come from one config file, and the hosted page serves the data files as they stand.

Repo layout:

- /pipeline: Python scripts that fetch, clean, build crosswalks and compute scores
- /config: scores.yaml (every score and ratio definition) and modules.yaml (each module's metrics, scores and buy-box presets)
- /data: the JSON output, keyed on GEOID plus vintage year
- /web: the static HTML page
- CLAUDE.md: the rules file in the repo root

## Sharing and hosting

Start with a hosted, view-only link on a free static host such as GitHub Pages or Netlify. The page reads only pre-built JSON files, so there is no server to run and nothing sensitive in the browser.

- The Census API key stays in the pipeline's environment, never in the repo or the page.
- Refreshing data means re-running the pipeline and republishing.
- Add logins only if you want saved custom areas or private acquisition targets. That would also be the point to move to Streamlit or React.

## Phased build plan

Build one county end to end, then widen. Each phase starts only after the previous gate passes. Start with Phase 1.

| Phase | Scope | Gate to pass before the next phase |
| --- | --- | --- |
| 1. Davis County | Core pipeline; map and delta cards; schools and score key | Davis numbers match source tables |
| 2. Utah | All Utah areas; district crosswalk; screener and Gardner data | Screen all Utah cities with your own buy box |
| 3. National | All states loaded; state peer groups; no Utah-only code | Any state loads and scores without Utah-specific code |
| 4. Tracts and ZIP | Tract map layer; ZIP lookup; map settings | Tract layer works for any county |

Phase 1 proves the whole chain on one county before Utah and the national load. The gate criteria are proposals; edit them as needed. The multifamily, townhome and underwriting-context modules are mostly presets on core data, so they can ship in Phase 1 too. Industrial and retail need the added sources above, so plan them after Gate 1.

## Open questions and risks

| Item | Why it matters | Proposed handling |
| --- | --- | --- |
| Buy-box thresholds | The screener is only as useful as your limits | You set minimums and maximums for growth, income, permits and enrollment; saved as presets |
| Charter students | Charter schools have no attendance boundary, so their students do not map cleanly to a city | Report charter enrollment at district and county level, plus school locations on the map |
| City and school district overlap | Boundaries do not nest | Crosswalk tables with overlap shares; label school figures as district-based |
| Small-city reliability | ACS estimates for small places carry large margins of error | Store and display margins of error; flag unreliable values |
| Projections outside Utah | Gardner Institute projections cover Utah only | Treat as an add-on layer; use trend-based estimates elsewhere |
| Reference score formulas | The video does not show how its composite scores are calculated | Define our own formulas (above) and document them in the app |
| Source terms and release timing | Endpoints, tables and release schedules change | Verify each source in Phase 1 and record it in the pipeline config |
