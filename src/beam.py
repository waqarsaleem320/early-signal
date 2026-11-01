"""Human-health stream — CDC BEAM Dashboard "Report Data" export.

BEAM is PulseNet-derived: laboratory-confirmed isolates by state, month,
source type (Human / Food / Animal / Environment), pathogen and serotype,
2018 onward. Unlike NORS it counts every confirmed case, not only those linked
to a recognized outbreak, so it is the forecast target.

The most recent month in an export is usually incomplete (isolates are still
being reported), so `complete_through()` returns the last month treated as
final.
"""
from __future__ import annotations

import pandas as pd

from . import config, geo

# Serotypes most often found in FSIS raw poultry positives (FY2018-2026).
POULTRY_SEROTYPES: tuple[str, ...] = (
    "Enteritidis", "Infantis", "Typhimurium", "Heidelberg",
    "Schwarzengrund", "Hadar",
)
PROVISIONAL_MONTHS = 1  # trailing months treated as incomplete
# 50 states + DC; BEAM also carries territories and malformed codes.
US_STATES: frozenset[str] = frozenset(
    a for a in geo.ABBR_TO_STATE_NAME if a not in {"PR", "GU", "VI", "AS", "MP"})


def load_beam_raw() -> pd.DataFrame:
    """Newest BEAM export with clean numeric Year/Month."""
    files = sorted(config.DATA_DIR.glob(config.BEAM_REPORT_PATTERN))
    if not files:
        raise FileNotFoundError(
            f"No BEAM export matching '{config.BEAM_REPORT_PATTERN}' in {config.DATA_DIR}. "
            "Export it from data.cdc.gov (BEAM Dashboard - Report Data) as CSV.")
    df = pd.read_csv(files[-1], low_memory=False)
    df["Year"] = pd.to_numeric(df["Year"].astype(str).str.replace(",", ""), errors="coerce")
    df["Month"] = pd.to_numeric(df["Month"], errors="coerce")
    df["Number of isolates"] = pd.to_numeric(df["Number of isolates"], errors="coerce").fillna(0)
    return df.dropna(subset=["Year", "Month", "State"])


def human_isolates(pathogen: str = "Salmonella",
                   serotypes: tuple[str, ...] | None = None) -> pd.DataFrame:
    """Human isolates per (state, year, month), zero-filled over the full grid."""
    df = load_beam_raw()
    df = df[(df["Source Type"] == "Human") & (df["Pathogen"] == pathogen)
            & df["State"].isin(US_STATES)]
    if serotypes:
        df = df[df["Serotype/Species"].isin(serotypes)]
    counts = (df.groupby(["State", "Year", "Month"])["Number of isolates"].sum()
              .rename("isolates").reset_index()
              .rename(columns={"State": "state", "Year": "year", "Month": "month"}))
    states = counts["state"].unique()
    periods = pd.period_range(
        pd.Period(year=int(counts["year"].min()), month=1, freq="M"),
        pd.Period(year=int(counts["year"].max()),
                  month=int(counts.loc[counts["year"] == counts["year"].max(), "month"].max()),
                  freq="M"),
        freq="M")
    grid = pd.MultiIndex.from_product([states, periods], names=["state", "period"]).to_frame(index=False)
    grid["year"] = grid["period"].dt.year
    grid["month"] = grid["period"].dt.month
    out = grid.merge(counts, on=["state", "year", "month"], how="left")
    out["isolates"] = out["isolates"].fillna(0)
    for c in ("year", "month"):
        out[c] = out[c].astype(int)
    return out.drop(columns="period")


def nonhuman_isolates(pathogen: str = "Salmonella",
                      serotypes: tuple[str, ...] | None = None) -> pd.DataFrame:
    """Food, animal and environmental isolates per (state, year, month).

    These come from food/animal surveillance (largely poultry, e.g. FSIS and
    NARMS isolates sequenced in PulseNet), i.e. closer to the source than human
    cases. Only state-months with isolates are returned; absent = 0.
    """
    df = load_beam_raw()
    df = df[(df["Source Type"] != "Human") & (df["Pathogen"] == pathogen)
            & df["State"].isin(US_STATES)]
    if serotypes:
        df = df[df["Serotype/Species"].isin(serotypes)]
    out = (df.groupby(["State", "Year", "Month"])["Number of isolates"].sum()
           .rename("nonhuman_isolates").reset_index()
           .rename(columns={"State": "state", "Year": "year", "Month": "month"}))
    out["year"], out["month"] = out["year"].astype(int), out["month"].astype(int)
    return out


def complete_through(df: pd.DataFrame) -> pd.Period:
    """Last month treated as complete (drops PROVISIONAL_MONTHS trailing months)."""
    last = pd.Period(year=int(df["year"].max()),
                     month=int(df.loc[df["year"] == df["year"].max(), "month"].max()), freq="M")
    return last - PROVISIONAL_MONTHS


__all__ = ["POULTRY_SEROTYPES", "US_STATES", "load_beam_raw", "human_isolates", "nonhuman_isolates",
           "complete_through"]
