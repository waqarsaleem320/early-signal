"""Environment stream — NOAA statewide climate (nClimDiv) and Storm Events.

Both sources are reduced to one row per (state, year, month) so they join the
forecast panel directly.

nClimDiv record layout (see data/state-readme.txt):
    cols 1-3 state code, 4 division (0), 5-6 element, 7-10 year,
    then 12 monthly values; -99.90 / -9.99 mark months not yet available.
State codes are alphabetical for the lower 48, then 049 Hawaii, 050 Alaska;
codes above 100 are regions and are dropped.

Anomalies are computed against the 1991-2020 normal for the same state and
calendar month, so they measure "hotter/wetter than usual for here and now",
which is what weather can add on top of seasonality.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import config, geo

_CLIMDIV_STATES = [
    "Alabama", "Arizona", "Arkansas", "California", "Colorado", "Connecticut",
    "Delaware", "Florida", "Georgia", "Idaho", "Illinois", "Indiana", "Iowa",
    "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland", "Massachusetts",
    "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska",
    "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming", "Hawaii", "Alaska",
]
CLIMDIV_STATE_CODES: dict[int, str] = {
    i + 1: geo.to_abbr(name) for i, name in enumerate(_CLIMDIV_STATES)
}
NORMAL_PERIOD = (1991, 2020)

# Storm Events EVENT_TYPE -> category used as features.
STORM_CATEGORIES: dict[str, list[str]] = {
    "heat": ["Heat", "Excessive Heat"],
    "flood": ["Flood", "Flash Flood", "Heavy Rain", "Coastal Flood", "Lakeshore Flood"],
    "tropical": ["Hurricane", "Hurricane (Typhoon)", "Tropical Storm",
                 "Tropical Depression", "Storm Surge/Tide"],
    "severe": ["Thunderstorm Wind", "Tornado", "Hail", "High Wind", "Strong Wind"],
    "winter": ["Winter Storm", "Winter Weather", "Heavy Snow", "Ice Storm",
               "Blizzard", "Cold/Wind Chill", "Extreme Cold/Wind Chill", "Frost/Freeze"],
}


def _newest(pattern: str) -> Path:
    files = sorted(config.DATA_DIR.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No file matching '{pattern}' in {config.DATA_DIR}.")
    return files[-1]


# ---------------------------------------------------------------------------
# nClimDiv
# ---------------------------------------------------------------------------
def load_climdiv(element: str) -> pd.DataFrame:
    """One climate element as (state, year, month, value) for the 50 states."""
    path = _newest(config.CLIMDIV_PATTERNS[element])
    rows = []
    with path.open() as fh:
        for line in fh:
            if len(line) < 20:
                continue
            code = int(line[0:3])
            state = CLIMDIV_STATE_CODES.get(code)
            if state is None:
                continue
            year = int(line[6:10])
            vals = [float(v) for v in line[10:].split()[:12]]
            rows.extend((state, year, m + 1, v) for m, v in enumerate(vals))
    df = pd.DataFrame(rows, columns=["state", "year", "month", element])
    df.loc[df[element] <= -9.99, element] = np.nan
    return df


def load_climate() -> pd.DataFrame:
    """tmax, tavg, precip and their anomalies vs. the 1991-2020 normal."""
    out = None
    for element in config.CLIMDIV_PATTERNS:
        d = load_climdiv(element)
        out = d if out is None else out.merge(d, on=["state", "year", "month"], how="outer")
    base = out[out["year"].between(*NORMAL_PERIOD)]
    normals = base.groupby(["state", "month"])[list(config.CLIMDIV_PATTERNS)].mean()
    out = out.join(normals, on=["state", "month"], rsuffix="_normal")
    for element in config.CLIMDIV_PATTERNS:
        out[f"{element}_anom"] = out[element] - out[f"{element}_normal"]
    return out.drop(columns=[f"{e}_normal" for e in config.CLIMDIV_PATTERNS])


# ---------------------------------------------------------------------------
# Storm Events
# ---------------------------------------------------------------------------
def _parse_damage(s: pd.Series) -> pd.Series:
    """'1.5K' / '2M' / '0.1B' -> dollars."""
    s = s.astype("string").str.strip().str.upper().fillna("")
    mult = s.str[-1].map({"K": 1e3, "M": 1e6, "B": 1e9}).fillna(1.0)
    num = pd.to_numeric(s.str.rstrip("KMB"), errors="coerce").fillna(0.0)
    return num * mult


def load_storms(*, use_cache: bool = True) -> pd.DataFrame:
    """Storm event counts per category and property damage per state-month."""
    files = sorted(config.DATA_DIR.glob(config.STORM_EVENTS_PATTERN))
    if not files:
        raise FileNotFoundError(
            f"No Storm Events files matching '{config.STORM_EVENTS_PATTERN}' in {config.DATA_DIR}.")
    cache = config.DATA_CACHE_DIR / "storm_events_state_month.parquet"
    sig = "|".join(f"{p.name}:{p.stat().st_size}" for p in files)
    sig_path = cache.with_suffix(".sig")
    if use_cache and cache.exists() and sig_path.exists() and sig_path.read_text() == sig:
        return pd.read_parquet(cache)

    cols = ["STATE", "BEGIN_YEARMONTH", "EVENT_TYPE", "DAMAGE_PROPERTY", "DEATHS_DIRECT"]
    ev = pd.concat([pd.read_csv(p, usecols=cols, low_memory=False) for p in files],
                   ignore_index=True)
    ev["state"] = ev["STATE"].astype(str).str.title().map(geo.to_abbr)
    ev = ev.dropna(subset=["state"])
    ev["year"] = ev["BEGIN_YEARMONTH"] // 100
    ev["month"] = ev["BEGIN_YEARMONTH"] % 100
    ev["damage_usd"] = _parse_damage(ev["DAMAGE_PROPERTY"])
    type_to_cat = {t: c for c, ts in STORM_CATEGORIES.items() for t in ts}
    ev["category"] = ev["EVENT_TYPE"].map(type_to_cat).fillna("other")

    keys = ["state", "year", "month"]
    counts = (ev.pivot_table(index=keys, columns="category", values="EVENT_TYPE",
                             aggfunc="size", fill_value=0)
              .add_prefix("storm_").reset_index())
    agg = ev.groupby(keys).agg(storm_events=("EVENT_TYPE", "size"),
                               storm_damage_musd=("damage_usd", lambda x: x.sum() / 1e6),
                               storm_deaths=("DEATHS_DIRECT", "sum")).reset_index()
    out = agg.merge(counts, on=keys, how="left")
    out.columns.name = None
    if use_cache:
        config.DATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out.to_parquet(cache, index=False)
        sig_path.write_text(sig)
    return out


__all__ = ["CLIMDIV_STATE_CODES", "STORM_CATEGORIES", "load_climdiv", "load_climate",
           "load_storms"]
