"""CDC/ATSDR Social Vulnerability Index loader."""
from __future__ import annotations

import pandas as pd

from . import config

# ---------------------------------------------------------------------------
# CDC / ATSDR Social Vulnerability Index (SVI), county level, 2000-2022
# ---------------------------------------------------------------------------
# Normalized output schema (one row per county per vintage):
#   svi_year      int   : vintage year
#   FIPS          str   : 5-digit county FIPS (zero-padded)
#   state         str   : state abbreviation (or name for 2000)
#   county        str   : county name
#   svi_overall   float : overall SVI percentile ranking in [0, 1]
#                         (RPL_THEMES / R_PL_THEMES; derived for 2000)
#   svi_theme1..4 float : the four theme percentile rankings where available
#
# The percentile ranking is the ATSDR summary used for equity comparison: a
# value near 1.0 = most vulnerable. Missing values (-999 sentinel) -> NaN.
SVI_NORMALIZED_COLUMNS = (
    "svi_year",
    "FIPS",
    "state",
    "county",
    "svi_overall",
    "svi_theme1",
    "svi_theme2",
    "svi_theme3",
    "svi_theme4",
)


def _clean_svi_sentinels(df: pd.DataFrame) -> pd.DataFrame:
    """Replace ATSDR -999 missing sentinels with NaN (numeric columns only)."""
    return df.replace(config.SVI_MISSING_SENTINEL, pd.NA)


def _normalize_svi_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Map one vintage's native columns onto the common normalized schema."""
    cols = set(df.columns)
    out = pd.DataFrame()
    out["svi_year"] = [year] * len(df)

    # --- FIPS (5-digit string) -------------------------------------------
    if "FIPS" in cols:
        fips = df["FIPS"].astype("string")
    elif {"STATE_FIPS", "CNTY_FIPS"}.issubset(cols):
        # 2000: combine 2-digit state + 3-digit county.
        fips = (
            df["STATE_FIPS"].astype("string").str.zfill(2)
            + df["CNTY_FIPS"].astype("string").str.zfill(3)
        )
    elif "STCOFIPS" in cols:
        fips = df["STCOFIPS"].astype("string")
    elif "STCNTY" in cols:
        fips = df["STCNTY"].astype("string")
    else:
        fips = pd.Series([pd.NA] * len(df), dtype="string")
    out["FIPS"] = fips.str.replace(r"\.0$", "", regex=True).str.zfill(5)

    # --- state / county labels -------------------------------------------
    if "ST_ABBR" in cols:
        out["state"] = df["ST_ABBR"].astype("string")
    elif "STATE_ABBR" in cols:
        out["state"] = df["STATE_ABBR"].astype("string")
    elif "STATE" in cols:
        out["state"] = df["STATE"].astype("string")
    elif "STATE_NAME" in cols:
        out["state"] = df["STATE_NAME"].astype("string")
    else:
        out["state"] = pd.NA

    for name_col in ("COUNTY", "LOCATION"):
        if name_col in cols:
            out["county"] = df[name_col].astype("string")
            break
    else:
        out["county"] = pd.NA

    # --- overall + theme rankings ----------------------------------------
    # 2014+: RPL_THEMES / RPL_THEME1..4. 2010: R_PL_THEMES (no per-theme
    # standardized rankings in the same naming). 2000: no RPL at all.
    def _num(colname: str):
        return pd.to_numeric(df[colname], errors="coerce") if colname in cols else pd.NA

    if "RPL_THEMES" in cols:
        out["svi_overall"] = _num("RPL_THEMES")
    elif "R_PL_THEMES" in cols:
        out["svi_overall"] = _num("R_PL_THEMES")
    else:
        out["svi_overall"] = pd.NA  # 2000 handled below

    out["svi_theme1"] = _num("RPL_THEME1")
    out["svi_theme2"] = _num("RPL_THEME2")
    out["svi_theme3"] = _num("RPL_THEME3")
    out["svi_theme4"] = _num("RPL_THEME4")

    # 2000 special case: no precomputed overall percentile. ATSDR's 2000
    # product reports per-variable rankings (G*R) and USG* summaries rather
    # than a single 0-1 RPL_THEMES. Derive a comparable overall percentile by
    # percentile-ranking the count of flagged variables (USG*F fields), so the
    # 2000 vintage still yields a usable, monotonic vulnerability score. This
    # is an approximation and is flagged as such in the loader docstring.
    if year == 2000:
        flag_cols = [c for c in df.columns if c.upper().startswith("USG") and c.upper().endswith("F")]
        if flag_cols:
            flags = df[flag_cols].apply(pd.to_numeric, errors="coerce")
            total_flags = flags.sum(axis=1, min_count=1)
            out["svi_overall"] = total_flags.rank(pct=True)

    out = _clean_svi_sentinels(out)
    # Coerce ranking columns to float (NA-aware).
    for c in ("svi_overall", "svi_theme1", "svi_theme2", "svi_theme3", "svi_theme4"):
        out[c] = pd.to_numeric(out[c], errors="coerce")

    # Drop stray header/key rows: some ATSDR files (e.g. 2000) carry a second
    # label row whose FIPS is non-numeric ('STCOU'). A valid county FIPS is 5
    # digits; filter anything that isn't all-digits.
    valid_fips = out["FIPS"].str.fullmatch(r"\d{5}")
    out = out.loc[valid_fips.fillna(False)].reset_index(drop=True)
    return out[list(SVI_NORMALIZED_COLUMNS)]


def load_svi(year: int, *, normalized: bool = True) -> pd.DataFrame:
    """Load one ATSDR SVI county vintage.

    Parameters
    ----------
    year:
        One of the available vintages (2000, 2010, 2014, 2016, 2018, 2020, 2022).
    normalized:
        If True (default), return the common normalized schema
        (SVI_NORMALIZED_COLUMNS). If False, return the raw file as-is.

    Notes
    -----
    The 2000 vintage lacks a precomputed overall percentile (RPL_THEMES); its
    `svi_overall` is an approximation derived by percentile-ranking the number
    of flagged vulnerability variables. 2010+ use ATSDR's published rankings
    directly.
    """
    if year not in config.SVI_COUNTY_FILES:
        valid = ", ".join(str(y) for y in sorted(config.SVI_COUNTY_FILES))
        raise KeyError(f"No SVI file for year {year}. Available: {valid}")
    path = config.SVI_COUNTY_FILES[year]
    if not path.exists():
        raise FileNotFoundError(f"SVI {year} file not found at {path}.")

    raw = pd.read_csv(path, low_memory=False)
    if not normalized:
        return raw
    return _normalize_svi_year(raw, year)


def load_svi_all(normalized: bool = True) -> pd.DataFrame:
    """Load and vertically concatenate every available SVI vintage.

    Only meaningful with normalized=True (schemas differ across years). Returns
    a long frame with one row per county per vintage, carrying `svi_year`.
    """
    if not normalized:
        raise ValueError("load_svi_all requires normalized=True (schemas differ by year).")
    frames = [load_svi(y, normalized=True) for y in sorted(config.SVI_COUNTY_FILES)
              if config.SVI_COUNTY_FILES[y].exists()]
    if not frames:
        return pd.DataFrame(columns=list(SVI_NORMALIZED_COLUMNS))
    return pd.concat(frames, ignore_index=True)


def load_svi_vulnerability(year: int = 2022) -> pd.DataFrame:
    """County-level vulnerable-population profile for the equity map.

    Joins the ATSDR SVI estimates that describe the groups the donation
    routing is meant to protect with Census county centroids (lat/lon):

      population      E_TOTPOP   total residents
      pct_age65       EP_AGE65   % aged 65+                  (elderly)
      pct_age17       EP_AGE17   % aged 17 and younger       (children)
      pct_disabled    EP_DISABL  % with a disability         (medical-vulnerability proxy)
      pct_uninsured   EP_UNINSUR % without health insurance  (medical-access proxy)
      pct_pov150      EP_POV150  % below 150% of poverty     (food-insecurity proxy)
      svi_overall     RPL_THEMES overall SVI percentile (0-1)

    SVI does not measure immunocompromise or malnutrition directly; disability,
    uninsured, and poverty are the closest published proxies.
    """
    raw = load_svi(year, normalized=False)
    cols = {"E_TOTPOP": "population", "EP_AGE65": "pct_age65",
            "EP_AGE17": "pct_age17", "EP_DISABL": "pct_disabled",
            "EP_UNINSUR": "pct_uninsured", "EP_POV150": "pct_pov150",
            "RPL_THEMES": "svi_overall"}
    present = {k: v for k, v in cols.items() if k in raw.columns}
    df = raw[["FIPS", "ST_ABBR", "COUNTY"] + list(present)].rename(
        columns={"ST_ABBR": "state", "COUNTY": "county", **present})
    df["FIPS"] = df["FIPS"].astype("string").str.replace(r"\.0$", "", regex=True).str.zfill(5)
    for c in present.values():
        df[c] = pd.to_numeric(df[c], errors="coerce")
        df.loc[df[c] == config.SVI_MISSING_SENTINEL, c] = pd.NA
        df[c] = df[c].astype("float64")

    cent = pd.read_csv(config.COUNTY_CENTROIDS_CSV, dtype={"FIPS": str})
    cent["FIPS"] = cent["FIPS"].str.zfill(5)
    df = df.merge(cent[["FIPS", "lat", "lon"]], on="FIPS", how="inner")
    return df.dropna(subset=["svi_overall", "lat", "lon"]).reset_index(drop=True)


__all__ = ["load_svi", "load_svi_vulnerability"]
