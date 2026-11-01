"""Centralized, secure configuration for the PoultryRescue (SENS-D) pipeline.

Security guardrail (Step 1): API credentials are NEVER hardcoded. Every token
is pulled at runtime via os.getenv() after loading the local `.env` file with
python-dotenv. The `.env` file is gitignored; `.env.examples` documents the
expected variable names with empty values.

Usage:
    from src.config import settings
    token = settings.require("NOAA_TOKEN")
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Project paths (safe, relative, OS-independent via pathlib / os.path)
# ---------------------------------------------------------------------------
# config.py lives in <root>/src/, so the project root is one level up.
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
DATA_DIR: Path = PROJECT_ROOT / "data"
NOTEBOOKS_DIR: Path = PROJECT_ROOT / "notebooks"
ENV_PATH: Path = NOTEBOOKS_DIR / ".env"

# Load credentials from notebooks/.env into the process environment.
# `override=False` so real environment variables (e.g. CI secrets) win.
load_dotenv(dotenv_path=ENV_PATH, override=False)


# ---------------------------------------------------------------------------
# Local dataset locations
# ---------------------------------------------------------------------------
NORS_XLSX: Path = DATA_DIR / "NORS.xlsx"
NORS_DICTIONARY_XLSX: Path = DATA_DIR / "NORS-Flat-DataDictionary-508_JAN2025_CLEAN.xlsx"

# CDC/ATSDR SVI county files, keyed by vintage year. The schema differs by
# era (2000 uses USG* percentiles + split FIPS; 2010 uses R_PL_THEMES; 2014+
# use RPL_THEME1..4 + RPL_THEMES). src.ingest_local.load_svi normalizes them.
SVI_COUNTY_FILES: dict[int, Path] = {
    2000: DATA_DIR / "SVI_2000_US_COUNTY.csv",
    2010: DATA_DIR / "SVI_2010_US_COUNTY.csv",
    2014: DATA_DIR / "SVI_2014_US_COUNTY.csv",
    2016: DATA_DIR / "SVI_2016_US_COUNTY.csv",
    2018: DATA_DIR / "SVI_2018_US_COUNTY.csv",
    2020: DATA_DIR / "SVI_2020_US_COUNTY.csv",
    2022: DATA_DIR / "SVI_2022_US_COUNTY.csv",
}
# ATSDR missing-value sentinel used across SVI vintages.
SVI_MISSING_SENTINEL = -999

# U.S. Census 2023 Gazetteer county internal points (lat/lon per county FIPS).
# Public download, trimmed to FIPS/state/lat/lon. Used to route donations to
# real nearby counties instead of state centroids.
COUNTY_CENTROIDS_CSV: Path = DATA_DIR / "county_centroids_2023.csv"

# FSIS Raw Poultry Sampling (REAL, establishment-specific) — one file per fiscal
# year, downloaded from the FSIS Laboratory Sampling Data page. Both the FSIS
# zip as downloaded (raw_poultry_sampling_data_fy<YYYY>.zip) and an extracted
# JSON (fsis_raw_poultry_sampling_fy<YYYY>.json) are accepted. Every matching
# file is loaded, so adding a fiscal year needs no code change.
FSIS_RAW_POULTRY_PATTERNS: tuple[str, ...] = (
    "raw_poultry_sampling_data_fy*.zip",
    "fsis_raw_poultry_sampling_fy*.json",
)

# Regenerable caches (parquet) of slow-to-parse sources; gitignored.
DATA_CACHE_DIR: Path = PROJECT_ROOT / "data_cache"

# NOAA NCEI nClimDiv statewide monthly climate (fixed-width text, no extension).
# tmaxst = max temperature (F), tmpcst = average temperature (F),
# pcpnst = precipitation (inches). Newest release per element is used.
CLIMDIV_PATTERNS: dict[str, str] = {
    "tmax": "climdiv-tmaxst-v*",
    "tavg": "climdiv-tmpcst-v*",
    "precip": "climdiv-pcpnst-v*",
}

# NOAA Storm Events Database, "details" files (one gzipped CSV per year).
STORM_EVENTS_PATTERN: str = "StormEvents_details-ftp_v1.0_d*_c*.csv.gz"

# CDC BEAM Dashboard "Report Data" export (PulseNet-derived isolates by state,
# month, source type, pathogen and serotype). Newest export is used.
BEAM_REPORT_PATTERN: str = "BEAM_Dashboard_-_Report_Data_*.csv"

# County boundaries (GeoJSON keyed by 5-digit FIPS) for county choropleths.
# Fetched once from the URL below and cached here if missing.
COUNTY_GEOJSON: Path = DATA_DIR / "geojson-counties-fips.json"
COUNTY_GEOJSON_URL = (
    "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
)


# ---------------------------------------------------------------------------
# API endpoints (public URLs — not secrets)
# ---------------------------------------------------------------------------
NOAA_GHCND_BASE = "https://www.ncei.noaa.gov/cdo-web/api/v2"
NASS_QUICKSTATS_BASE = "https://quickstats.nass.usda.gov/api/api_GET/"
AMS_MARS_BASE = "https://marsapi.ams.usda.gov/services/v1.2"
CENSUS_BASE = "https://api.census.gov/data"

# CDC Socrata v3 query endpoints (BEAM Dashboard + NORS). Public, keyless.
CDC_SOCRATA_ENDPOINTS: dict[str, str] = {
    "beam_report_data": "https://data.cdc.gov/api/v3/views/jbhn-e8xn/query.csv",
    "beam_isolates_by_hhs_region": "https://data.cdc.gov/api/v3/views/khic-yj26/query.csv",
    "beam_top30_serotypes": "https://data.cdc.gov/api/v3/views/ch83-ush6/query.csv",
    "beam_serotypes_concern_illnesses_outbreaks": "https://data.cdc.gov/api/v3/views/fvm6-ic5r/query.csv",
    "beam_serotypes_concern_burden_trajectory": "https://data.cdc.gov/api/v3/views/8na9-qgz7/query.csv",
    "nors": "https://data.cdc.gov/api/v3/views/5xkq-dg7x/query.csv",
}


@dataclass(frozen=True)
class Settings:
    """Runtime settings. Credential *values* are read lazily and never stored
    as attributes, so they cannot be accidentally logged or serialized."""

    env_names: tuple[str, ...] = field(
        default=(
            "NOAA_TOKEN",
            "CENSUS_API_KEY",
            "NASS_API_KEY",
            "AMS_API_KEY",
        )
    )

    def get(self, name: str, default: str | None = None) -> str | None:
        """Return a credential value or `default` if unset. Never logs the value."""
        return os.getenv(name, default)

    def require(self, name: str) -> str:
        """Return a credential value, raising a clear error if it is missing.

        The error message references the variable *name* only — never a value —
        and points the user to the `.env` setup.
        """
        value = os.getenv(name)
        if not value:
            raise RuntimeError(
                f"Required credential '{name}' is not set. "
                f"Copy notebooks/.env.examples to notebooks/.env and fill in '{name}'. "
                f"Credentials are loaded via os.getenv() and must never be hardcoded."
            )
        return value

    def status(self) -> dict[str, bool]:
        """Return which credentials are present WITHOUT revealing their values.

        Useful for a notebook sanity check: prints True/False per key only.
        """
        return {name: bool(os.getenv(name)) for name in self.env_names}


settings = Settings()
