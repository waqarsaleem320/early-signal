"""
Poultry cooking-yield lookup (USDA data), from PoultryRescue.

Wraps the USDA Table of Cooking Yields for Meat and Poultry (Release 2) so the
rescue/prepare logic can look up a realistic cooking yield for a given poultry
product form AND cooking method. Every returned yield is a real USDA study value
(USDA_ACTUAL); nothing is interpolated or invented. When an exact product+method
match is not available, we fall back step-by-step and report HOW the match was
made so the provenance stays transparent.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

POULTRY_FOOD_GROUP = "5"

# Canonical product forms -> keywords to find them in the Yield Description.
FORM_KEYWORDS: dict[str, list[str]] = {
    "breast": ["breast"],
    "thigh": ["thigh"],
    "drumstick": ["drumstick"],
    "wing": ["wing"],
    "back": ["back"],
    "neck": ["neck"],
    "whole": ["whole", "broiler-fryer, whole"],
    "dark meat": ["dark meat"],
    "gizzard": ["gizzard"],
    "liver": ["liver"],
    "heart": ["heart"],
    "giblets": ["giblet"],
    "turkey breast": ["turkey", "breast"],
    "turkey whole": ["turkey, whole"],
    "turkey thigh": ["turkey", "thigh"],
    "turkey drumstick": ["turkey", "drumstick"],
    "turkey wing": ["turkey", "wing"],
    "turkey dark meat": ["turkey", "dark meat"],
}

# Canonical cooking methods -> keywords to find them in Preparation Method.
METHOD_KEYWORDS: dict[str, list[str]] = {
    "roasted": ["roasted", "baked"],
    "braised": ["braised"],
    "simmered": ["poached", "simmered", "stewed", "moist"],
    "fried": ["fried in deep fat", "deep fat"],
    "pan-fried": ["pan-fried", "sauteed", "sautéed"],
}


@dataclass
class YieldMatch:
    found: bool
    cooking_yield_pct: float | None
    ndb: str | None
    description: str | None
    preparation_method: str | None
    match_quality: str       # 'exact' | 'form-only' | 'poultry-fallback' | 'none'
    provenance: str = "USDA_ACTUAL"


def _poultry(df: pd.DataFrame) -> pd.DataFrame:
    fg = [c for c in df.columns if c.lower().startswith("food group")][0]
    return df[df[fg].astype(str).str.strip() == POULTRY_FOOD_GROUP]


def available_forms(df: pd.DataFrame) -> list[str]:
    """Which canonical product forms are actually present in the data."""
    poultry = _poultry(df)
    dcol = [c for c in df.columns if c.lower().startswith("yield desc")][0]
    descs = poultry[dcol].str.lower()
    out = []
    for form, keys in FORM_KEYWORDS.items():
        if descs.apply(lambda d: all(k in d for k in keys)).any():
            out.append(form)
    return out


def lookup_yield(df: pd.DataFrame, product_form: str,
                 method: str | None = None) -> YieldMatch:
    """Return a real USDA cooking yield for product_form (+ optional method).

    Fallback order: exact (form+method) -> form only -> any poultry row.
    """
    poultry = _poultry(df)
    dcol = [c for c in df.columns if c.lower().startswith("yield desc")][0]
    pcol = [c for c in df.columns if c.lower().startswith("preparation")][0]
    ycol = [c for c in df.columns if c.lower().startswith("cooking yield")][0]

    form_keys = FORM_KEYWORDS.get(product_form.lower(), [product_form.lower()])
    desc = poultry[dcol].str.lower()
    form_mask = desc.apply(lambda d: all(k in d for k in form_keys))
    form_rows = poultry[form_mask]

    def build(row, quality):
        return YieldMatch(
            found=True,
            cooking_yield_pct=float(pd.to_numeric(row[ycol], errors="coerce")),
            ndb=str(row["NDB"]),
            description=str(row[dcol]),
            preparation_method=str(row[pcol]),
            match_quality=quality,
        )

    # 1) exact form + method
    if method and not form_rows.empty:
        mkeys = METHOD_KEYWORDS.get(method.lower(), [method.lower()])
        prep = form_rows[pcol].str.lower()
        m_mask = prep.apply(lambda p: any(k in p for k in mkeys))
        if m_mask.any():
            return build(form_rows[m_mask].iloc[0], "exact")

    # 2) form only
    if not form_rows.empty:
        return build(form_rows.iloc[0], "form-only")

    # 3) any poultry row
    if not poultry.empty:
        return build(poultry.iloc[0], "poultry-fallback")

    return YieldMatch(False, None, None, None, None, "none")


def yield_options_for_form(df: pd.DataFrame, product_form: str) -> pd.DataFrame:
    """All available (method, yield%) options for a product form - lets the user
    compare cooking methods and see which preserves the most product."""
    poultry = _poultry(df)
    dcol = [c for c in df.columns if c.lower().startswith("yield desc")][0]
    pcol = [c for c in df.columns if c.lower().startswith("preparation")][0]
    ycol = [c for c in df.columns if c.lower().startswith("cooking yield")][0]
    form_keys = FORM_KEYWORDS.get(product_form.lower(), [product_form.lower()])
    desc = poultry[dcol].str.lower()
    rows = poultry[desc.apply(lambda d: all(k in d for k in form_keys))]
    out = rows[["NDB", dcol, pcol, ycol]].copy()
    out.columns = ["NDB", "Yield Description", "Preparation Method",
                   "Cooking Yield % (USDA_ACTUAL)"]
    return out.sort_values("Cooking Yield % (USDA_ACTUAL)",
                           ascending=False).reset_index(drop=True)
