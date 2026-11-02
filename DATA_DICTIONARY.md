# Data Dictionary and Provenance

All data are public. `scripts/build_derived_data.py` shows how derived files were made. Files are in `data/` unless noted.

| Dataset | File | Source | Access date | License | Geography | Time | Updates | Changes made | Limits |
|---|---|---|---|---|---|---|---|---|---|
| CDC BEAM report data | `BEAM_Dashboard_-_Report_Data_20261029.csv` | https://data.cdc.gov (view jbhn-e8xn) | 2026-10-29 (file name) | US Gov public domain | State | 2018 to Sept 2026 | Monthly | Human isolates by state and month; last month dropped as provisional | Recent months may still change; PulseNet-derived; not linked to a food source |
| CDC NORS outbreaks | `NORS.xlsx` | Provided by organizers; https://wwwn.cdc.gov/norsdashboard/ | 2026-10-26 | US Gov public domain | State of exposure | 2014 to 2024 | Annual | Salmonella food outbreaks; first serotype slot for severity table | Reported outbreaks only; multistate outbreaks are not assigned to one state; 2020 reporting dip |
| FSIS raw poultry sampling | `raw_poultry_sampling_data_fy20*.zip` | https://www.fsis.usda.gov/news-events/publications/raw-poultry-sampling | 2026-10-26 | US Gov public domain | Plant state | Oct 2013 to June 2026 (routine projects from March 2015) | Quarterly | Routine projects only; product groups; no plant names shown | About 3-4 month lag; verification sampling, not a random survey; method changes over time |
| FSIS Salmonella categories | `Dataset_EstablishmentCategories_202609.xlsx` | https://www.fsis.usda.gov/news-events/publications/salmonella-verification-testing-august-31-2025-through-august-29-2026 | 2026-10-31 | US Gov public domain | Plant and product class | Aug 31 2025 to Aug 29 2026 | Monthly | Aggregate counts by product class; joined to rebuilt status for an agreement check; no plant shown | One-year window looks backward |
| FSIS Salmonella categories, earlier postings | `Dataset_EstablishmentCategories_202208.xlsx`, `_202308`, `_202408`, `_202509` | Internet Archive copies of https://www.fsis.usda.gov/sites/default/files/media_file/documents/ (same file names); data.gov dataset usda-fsis-025 | 2026-10-31 | US Gov public domain | Plant and product class | Sample windows ending Jul 30 2022, Jul 29 2023, Jul 27 2024, Jul 26 2025 | Monthly | Joined to later routine samples through the MPI directory; only aggregate rates shown | Archive copies, so check against FSIS if needed; closed plants drop out |
| FSIS MPI directory | `MPI_Directory_by_Establishment_Name.csv` | https://www.fsis.usda.gov/inspection/establishments/meat-poultry-and-egg-product-inspection-directory | October 2026 (exact date not recorded) | US Gov public domain | Plant | Current listing | Monthly | Establishment ID to number crosswalk only | Current plants only, so closed plants do not match |
| FSIS recalls and alerts | `fsis_recalls_2014_2026.csv` | https://www.fsis.usda.gov/fsis/api/recall/v/1 | 2026-10-31 | US Gov public domain | Distribution states | 2014 to Oct 2026 | Ongoing | English records; keyword flags for poultry and Salmonella | Flags need a manual check; plant numbers are not a clean field |
| NOAA nClimDiv | `climdiv-*st-*` | https://www.ncei.noaa.gov/monitoring-content/data/us/climdiv/monthly/current/ | October 2026 (NOAA file version 2026-10-06) | US Gov public domain | State | 1895 to 2026 | Monthly | Anomalies from 1991-2020 normals | Lower 48 states only; DC excluded from weather inputs |
| NOAA Storm Events | `StormEvents_details-*.csv.gz` | https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/ | October 2026 (latest file version c20261026) | US Gov public domain | State, county | 2014 to 2026 | Monthly | State-month counts by category | About 3 month lag; shows events, not power outages |
| CDC/ATSDR SVI 2022 | `SVI_2022_US_COUNTY.csv` | https://svi.cdc.gov/dataDownloads/data-download.html | October 2026 (exact date not recorded) | Public; cite CDC/ATSDR | County | ACS 2018-2022 | About every 2 years | Percentile, population, poverty share | One year used for all periods |
| USDA Food Access Research Atlas | `county_food_access_2019.csv` | https://www.ers.usda.gov/data-products/food-access-research-atlas/download-the-data | 2026-10-26 | US Gov public domain | County (from tract) | 2019 | Irregular | Low-income low-access population share by county | 2010 population base; older than SVI |
| CDC PLACES food insecurity | `places_county_foodinsecu_2025release.csv` | https://data.cdc.gov/resource/swc5-untb.csv?$where=measureid='FOODINSECU' | 2026-10-31 | Public domain | County | 2023 BRFSS, 2025 release | Annual | Crude prevalence used; added to need score | Modeled, not measured; adults only; 38 states and DC, missing CO, FL, KY, OR, PA, SD, TN, TX, VT, WA and WY |
| IRS food organizations | `irs_foodbank_pantry_orgs_ntee_K30-K35.csv` | https://www.irs.gov/pub/irs-soi/eo1.csv to eo4.csv | 2026-10-31 | Public domain | County, from ZIP | Current listing | Monthly | Filtered to NTEE K30, K31, K34, K35; county from ZCTA crosswalk | Approximate county; church-run pantries often missing; a listing does not confirm capacity |
| USDA cooking yields | `cooking_yields_poultry.csv` | USDA Table of Cooking Yields, Release 2, via the team's safety review work | October 2026 (exact date not recorded) | US Gov public domain | National | Static | Static | Poultry rows | No ground poultry row; most rows are meat and skin |
| USDA FoodData Central | `fdc_poultry_nutrition_pinned.csv` | https://api.nal.usda.gov/fdc/v1/ | 2026-10-31 | CC0 1.0 (USDA FoodData Central) | National | SR Legacy | Static | Pinned food IDs | Cooked meat values, not product-specific |
| County centroids | `county_centroids_2023.csv` | Census Gazetteer 2023, https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html | October 2026 (exact date not recorded) | US Gov public domain | County | 2023 | Annual | None | Centroids only |
| County boundaries | `geojson-counties-fips.json` | https://github.com/plotly/datasets | October 2026 (exact date not recorded) | No license stated in that repository; boundaries derive from US Census files (public domain) | County | Static | Static | None | Some FIPS missing |

Files in `data/` not used for results: `co-est2024-alldata.csv`, `SVI_2000` to `SVI_2020_US_COUNTY.csv`, the NORS documentation files and `state-readme.txt`.

## Fields used in results

| Field | Meaning |
|---|---|
| `expected_cases` | State forecast of poultry-associated human isolates for the month |
| `baseline_3y` | Mean of the same month in the three prior years |
| `outlook_ratio` | (expected + 5) / (baseline + 5) |
| `alert` | `outlook_ratio` at or above the threshold set on 2022-2023 |
| `surge` | Actual cases at least 30% and at least 5 above `baseline_3y` |
| `pct_positive_next_year` | Positivity in the 52 weeks after a line held this published or rebuilt category |
| `exposure_index` | Expected positivity for this product and category, relative to national chicken parts, times share sold raw |
| `servings_kept` | Cooked servings, 85 g each, using USDA cooking yield |
| `protein_kg` | Protein in those servings, from FoodData Central |
| `servings_to_need` | Servings donated to high-need counties, from the user's donated share |
| `need_score` | Mean percentile of SVI, low-income low-access share and CDC food insecurity, or the first two where PLACES has no estimate |
| `food_insecure_pct` | Adults reporting food insecurity in the past 12 months, modeled |
| `food_orgs` | Food banks and pantries on the IRS list in the county |
| `people_low_income` | County population times share below 150% of poverty |

## Assumptions the user can change

| Assumption | Default | Basis |
|---|---|---|
| Share of positives a test finds | 90% | Placeholder, not measured |
| Share donated after cooking | 25% | Placeholder, not measured |
| Time limit above 40°F | 2 hours | FSIS consumer guidance; the plant's HACCP critical limit governs |
| Lot size, plant category, cooked line | Entered per lot | User input |
