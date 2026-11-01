"""FSIS Raw Poultry Sampling — loader and hotspot statistics.

The REAL FSIS raw poultry Salmonella results (establishment-specific, one JSON
per fiscal year) are the upstream food+animal signal: they measure Salmonella
in product at the plant, before any outbreak is reported.

Why product-mix adjustment matters
----------------------------------
Positivity differs sharply by sample type (ground chicken ~26% vs. carcass
rinses ~5%). A state with many grinding plants looks worse regardless of real
risk. Hotspots are therefore ranked by the observed/expected ratio (O/E): the
expected count applies the national positivity of each sample type to the
state's own sample mix. O/E = 1.0 means "as expected for what was sampled".

Usage
-----
    from src import fsis_raw
    df = fsis_raw.load_raw_poultry()
    states = fsis_raw.state_summary(df)
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, geo

# Short, readable labels for FSIS sample_source_name values.
PRODUCT_GROUPS: dict[str, str] = {
    "Product-Raw-Intact-Chicken": "Chicken parts",
    "Animal-Chicken-Broiler / Young Chicken Carcass Rinse": "Chicken carcass",
    "Product-Raw-Ground, Comminuted or Otherwise Nonintact-Chicken": "Ground chicken",
    "Product-Raw-Ground, Comminuted or Otherwise Nonintact-Turkey": "Ground turkey",
    "Animal-Turkey-Turkey Carcass Sponge": "Turkey carcass",
}

# Region presets for the hotspot zoom (USPS abbreviations).
REGIONS: dict[str, list[str]] = {
    "Mid-Atlantic (Delmarva, MD, VA)": ["MD", "DE", "VA"],
    "Southeast broiler belt": ["GA", "AL", "MS", "AR", "NC", "SC"],
    "Carolinas": ["NC", "SC"],
    "Great Lakes": ["IL", "IN", "OH", "MI", "WI"],
    "California": ["CA"],
}

# Routine FSIS verification programs that ran consistently from FY2016 on.
# Follow-up sampling (targets plants that already failed), exploratory,
# intensified/outbreak, and very-low-volume projects are excluded from the
# risk signal: their positivity reflects FSIS targeting, not background risk.
ROUTINE_PROJECT_PREFIXES: tuple[str, ...] = (
    "HACCP Verification for Young",          # chicken and turkey carcasses
    "Sampling for Chicken Parts",            # legs, breasts, wings
    "Sampling for Ground and Other Comminuted",  # ground chicken and turkey
)

_PRIMARY_COLS = ["form_id", "establishment_id", "establishment_name",
                 "establishment_state", "project_name", "collection_date",
                 "sample_source_name", "product_type", "salmonella_sp_analysis"]
_SECONDARY_COLS = ["form_id", "salmonella_serotype", "salmonella_resistance_genotype"]
_CACHE_NAME = "fsis_raw_poultry.parquet"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def _fiscal_year(path: Path) -> int | None:
    m = re.search(r"fy(\d{4})", path.name, flags=re.IGNORECASE)
    return int(m.group(1)) if m else None


def raw_poultry_files() -> list[Path]:
    """One FSIS raw poultry file per fiscal year in data/, oldest first.

    Accepts the FSIS zip as downloaded or an extracted JSON; if both exist for
    the same fiscal year, the most recently modified file is used.
    """
    by_fy: dict[int, Path] = {}
    for pattern in config.FSIS_RAW_POULTRY_PATTERNS:
        for path in config.DATA_DIR.glob(pattern):
            fy = _fiscal_year(path)
            if fy is None:
                continue
            if fy not in by_fy or path.stat().st_mtime > by_fy[fy].stat().st_mtime:
                by_fy[fy] = path
    return [by_fy[fy] for fy in sorted(by_fy)]


def _read_json(path: Path) -> dict:
    """Return the inner FSIS object from a .json file or a .zip holding one."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            name = next(n for n in zf.namelist() if n.lower().endswith(".json"))
            obj = json.loads(zf.read(name))
    else:
        obj = json.loads(path.read_text(encoding="utf-8"))
    return obj[0] if isinstance(obj, list) else obj


def _read_one(path: Path) -> pd.DataFrame:
    """Load one fiscal-year file: primary results + first serotype per sample."""
    obj = _read_json(path)
    prim = pd.DataFrame(obj["data"]["primary_table_data"])
    sec = pd.DataFrame(obj["data"].get("secondary_table_data", []))

    prim = prim[[c for c in _PRIMARY_COLS if c in prim.columns]].copy()
    prim["form_id"] = prim["form_id"].astype(str)
    prim = prim[prim["salmonella_sp_analysis"].isin(["Positive", "Negative"])]

    if not sec.empty and "salmonella_serotype" in sec.columns:
        sec = sec[[c for c in _SECONDARY_COLS if c in sec.columns]].astype(str)
        sec = sec[~sec["salmonella_serotype"].isin(["NULL", "nan", ""])]
        sec = sec.drop_duplicates("form_id")
        prim = prim.merge(sec, on="form_id", how="left")

    prim["fiscal_year"] = _fiscal_year(path)
    return prim


def _cache_signature(files: list[Path]) -> str:
    return "|".join(f"{p.name}:{p.stat().st_size}:{int(p.stat().st_mtime)}" for p in files)


def load_raw_poultry(*, routine_only: bool = False, use_cache: bool = True) -> pd.DataFrame:
    """Load every FSIS raw poultry fiscal year into one tidy frame.

    Keeps only samples with a Salmonella result (Positive/Negative).
    Adds: positive (bool), product_group, routine (bool), month (Period),
    state (USPS). Parsing all fiscal years takes ~1 min, so the result is
    cached as parquet in data_cache/ and rebuilt automatically when files change.
    """
    files = raw_poultry_files()
    if not files:
        raise FileNotFoundError(
            f"No FSIS raw poultry files in {config.DATA_DIR} matching "
            f"{config.FSIS_RAW_POULTRY_PATTERNS}. Download them from the FSIS "
            "Laboratory Sampling Data page (Raw Poultry Sampling)."
        )

    cache = config.DATA_CACHE_DIR / _CACHE_NAME
    sig_path = cache.with_suffix(".sig")
    sig = _cache_signature(files)
    df = None
    if use_cache and cache.exists() and sig_path.exists() and sig_path.read_text() == sig:
        df = pd.read_parquet(cache)
    if df is None:
        df = pd.concat([_read_one(p) for p in files], ignore_index=True)
        df["positive"] = df["salmonella_sp_analysis"].eq("Positive")
        df["product_group"] = df["sample_source_name"].map(PRODUCT_GROUPS).fillna("Other")
        df["routine"] = df["project_name"].astype(str).str.startswith(ROUTINE_PROJECT_PREFIXES)
        df["collection_date"] = pd.to_datetime(df["collection_date"], errors="coerce")
        df["state"] = df["establishment_state"].map(geo.to_abbr)
        for c in ("salmonella_serotype", "salmonella_resistance_genotype"):
            if c not in df.columns:
                df[c] = pd.NA
        df["salmonella_serotype"] = (df["salmonella_serotype"].astype("string")
                                     .str.replace(" - Possible Vaccine Strain", "", regex=False))
        df = df.dropna(subset=["state", "collection_date"]).reset_index(drop=True)
        if use_cache:
            config.DATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            df.to_parquet(cache, index=False)
            sig_path.write_text(sig)

    # The parts program also tests comminuted parts. Those samples belong to parts, not ground product.
    parts = df["project_name"].astype(str).str.startswith("Sampling for Chicken Parts")
    df.loc[parts, "product_group"] = "Chicken parts"
    df["month"] = df["collection_date"].dt.to_period("M")
    if routine_only:
        df = df[df["routine"]].reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def _poisson_ci(observed: np.ndarray, z: float = 1.96) -> tuple[np.ndarray, np.ndarray]:
    """Byar's approximation to the exact Poisson 95% CI for an observed count."""
    o = np.asarray(observed, dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        lo = np.where(o > 0, o * (1 - 1 / (9 * o) - z / (3 * np.sqrt(o))) ** 3, 0.0)
    o1 = o + 1
    hi = o1 * (1 - 1 / (9 * o1) + z / (3 * np.sqrt(o1))) ** 3
    return lo, hi


MIN_HOTSPOT_PLANTS = 10  # below this a state result can reflect a single plant


def add_expected(df: pd.DataFrame) -> pd.DataFrame:
    """Expected positivity per sample = national rate of its product group
    (national = the frame passed in, so filters stay consistent)."""
    out = df.copy()
    out["expected"] = out["product_group"].map(out.groupby("product_group")["positive"].mean())
    return out


def state_summary(df: pd.DataFrame, min_samples: int = 100) -> pd.DataFrame:
    """Per-state positivity, product-mix-adjusted O/E with 95% CI, top serotype.

    `hotspot` is True when the lower CI bound of O/E is above 1, i.e. the state
    is significantly above what its sample mix predicts.
    """
    d = add_expected(df)
    g = d.groupby("state").agg(
        samples=("positive", "size"),
        positives=("positive", "sum"),
        expected=("expected", "sum"),
        plants=("establishment_id", "nunique"),
    )
    g["pct_positive"] = 100 * g["positives"] / g["samples"]
    g["o_e"] = g["positives"] / g["expected"]
    lo, hi = _poisson_ci(g["positives"].to_numpy())
    g["o_e_low"] = lo / g["expected"]
    g["o_e_high"] = hi / g["expected"]
    g["hotspot"] = (g["o_e_low"] > 1) & (g["plants"] >= MIN_HOTSPOT_PLANTS)

    sero = (d[d["positive"]].dropna(subset=["salmonella_serotype"])
            .groupby("state")["salmonella_serotype"]
            .agg(lambda s: s.value_counts().index[0]))
    g["top_serotype"] = sero
    g["state_name"] = g.index.map(geo.to_name)
    g = g[g["samples"] >= min_samples]
    return g.sort_values("o_e", ascending=False).round(
        {"pct_positive": 1, "o_e": 2, "o_e_low": 2, "o_e_high": 2, "expected": 1})


def monthly_positivity(df: pd.DataFrame, states: list[str] | None = None) -> pd.DataFrame:
    """Monthly positivity (raw %) and O/E for the given states (or all)."""
    d = add_expected(df)
    if states:
        d = d[d["state"].isin(states)]
    m = d.groupby("month").agg(samples=("positive", "size"),
                               positives=("positive", "sum"),
                               expected=("expected", "sum"))
    m["pct_positive"] = (100 * m["positives"] / m["samples"]).round(1)
    m["o_e"] = (m["positives"] / m["expected"]).round(2)
    m.index = m.index.to_timestamp()
    return m


def serotype_mix(df: pd.DataFrame, states: list[str] | None = None,
                 top_n: int = 6) -> pd.Series:
    """Share (%) of serotyped positives by serotype; the rest pooled as 'Other'."""
    d = df[df["positive"]].dropna(subset=["salmonella_serotype"])
    if states:
        d = d[d["state"].isin(states)]
    if d.empty:
        return pd.Series(dtype="float64")
    s = d["salmonella_serotype"].value_counts(normalize=True) * 100
    if len(s) > top_n:
        s = pd.concat([s.iloc[:top_n], pd.Series({"Other": s.iloc[top_n:].sum()})])
    return s.round(1)


def product_mix(df: pd.DataFrame, states: list[str] | None = None) -> pd.DataFrame:
    """Samples and positivity by product group (shows why O/E is needed)."""
    d = df[df["state"].isin(states)] if states else df
    p = d.groupby("product_group").agg(samples=("positive", "size"),
                                       pct_positive=("positive", "mean"))
    p["pct_positive"] = (100 * p["pct_positive"]).round(1)
    p["pct_of_samples"] = (100 * p["samples"] / p["samples"].sum()).round(1)
    return p.sort_values("samples", ascending=False)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
def load_county_geojson() -> dict:
    """County boundaries keyed by FIPS; downloaded once and cached in data/."""
    path = config.COUNTY_GEOJSON
    if not path.exists():
        import requests
        r = requests.get(config.COUNTY_GEOJSON_URL, timeout=60)
        r.raise_for_status()
        path.write_bytes(r.content)
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = ["PRODUCT_GROUPS", "REGIONS", "ROUTINE_PROJECT_PREFIXES", "raw_poultry_files", "load_raw_poultry",
           "add_expected", "state_summary", "monthly_positivity", "serotype_mix",
           "product_mix", "load_county_geojson"]
