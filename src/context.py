"""Measured context for a decision: product rates, plant categories, weather,
county need, and a live state outlook. Nothing here names a plant."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import config, forecast, fsis_raw, geo, ingest_local, outlook, weather

OUT_DIR = config.PROJECT_ROOT / "artifacts" / "context"
CATEGORY_XLSX = config.DATA_DIR / "Dataset_EstablishmentCategories_202609.xlsx"
FOOD_ACCESS_CSV = config.DATA_DIR / "county_food_access_2019.csv"
PLACES_CSV = config.DATA_DIR / "places_county_foodinsecu_2025release.csv"
FOOD_ORGS_CSV = config.DATA_DIR / "irs_foodbank_pantry_orgs_ntee_K30-K35.csv"
RECALLS_CSV = config.DATA_DIR / "fsis_recalls_2014_2026.csv"
WARM_MONTHS = (5, 6, 7, 8, 9, 10)
RATE_SINCE = pd.Timestamp("2023-06-01")
STORM_COLUMNS = ("storm_heat", "storm_flood", "storm_tropical")
MPI_CSV = config.DATA_DIR / "MPI_Directory_by_Establishment_Name.csv"
# FSIS maximum percent positive by product (81 FR 7285, 2016).
STANDARD_PCT = {"Chicken carcass": 9.8, "Chicken parts": 15.4, "Ground chicken": 25.0,
                "Turkey carcass": 7.1, "Ground turkey": 13.5}
PRODUCT_CLASSES = {"Young Chicken Carcasses": "Chicken carcass", "Chicken Parts": "Chicken parts",
                   "Comminuted Chicken": "Ground chicken", "Young Turkey Carcasses": "Turkey carcass",
                   "Comminuted Turkey": "Ground turkey"}
ANCHORS = ("2023-09-01", "2024-09-01", "2025-09-01")
CATEGORY_WINDOW = (pd.Timestamp("2025-08-31"), pd.Timestamp("2026-08-29"))
MIN_PLANT_SAMPLES = 10
SEED = 7
# Archived FSIS postings and the last day of each sample window.
PUBLISHED_POSTINGS = tuple((config.DATA_DIR / f"Dataset_EstablishmentCategories_{m}.xlsx", end) for m, end in (
    ("202208", "2022-07-30"), ("202308", "2023-07-29"), ("202408", "2024-07-27"), ("202509", "2025-07-26")))


def wilson(k: np.ndarray, n: np.ndarray, z: float = 1.96) -> tuple[np.ndarray, np.ndarray]:
    """Wilson 95% interval for a proportion."""
    k, n = np.asarray(k, float), np.asarray(n, float)
    p = k / n
    d = 1 + z ** 2 / n
    c = (p + z ** 2 / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / d
    return c - h, c + h


def product_rates() -> pd.DataFrame:
    """Routine FSIS positivity by product group and season, recent period only."""
    d = fsis_raw.load_raw_poultry(routine_only=True)
    d = d[d["collection_date"] >= RATE_SINCE].copy()
    d["season"] = np.where(d["collection_date"].dt.month.isin(WARM_MONTHS), "May-Oct", "Nov-Apr")
    g = (d.groupby(["product_group", "season"])["positive"].agg(samples="size", positives="sum")
         .reset_index())
    g = g[g["samples"] >= 100]
    g["pct_positive"] = (100 * g["positives"] / g["samples"]).round(1)
    lo, hi = wilson(g["positives"], g["samples"])
    g["ci_low"], g["ci_high"] = (100 * lo).round(1), (100 * hi).round(1)
    return g


def product_rate_validation() -> dict:
    """Does a product and season rate predict a sample's result better than one
    overall rate? Train through 2023, test from 2024 (Brier score, lower is better)."""
    d = fsis_raw.load_raw_poultry(routine_only=True)
    d = d.assign(warm=d["collection_date"].dt.month.isin(WARM_MONTHS).astype(int),
                 year=d["collection_date"].dt.year, y=d["positive"].astype(float))
    train, test = d[(d["year"] >= 2019) & (d["year"] <= 2023)], d[d["year"] >= 2024]
    overall = train["y"].mean()
    rates = train.groupby(["product_group", "warm"])["y"].mean().rename("p").reset_index()
    t = test.merge(rates, on=["product_group", "warm"], how="left").fillna({"p": overall})
    return {"test_samples": len(t), "overall_rate_train": round(float(overall), 4),
            "brier_overall": round(float(((overall - t["y"]) ** 2).mean()), 5),
            "brier_product_season": round(float(((t["p"] - t["y"]) ** 2).mean()), 5)}


def plant_persistence(min_samples: int = 5) -> pd.DataFrame:
    """How often a plant with a high quarter is high again next quarter."""
    d = fsis_raw.add_expected(fsis_raw.load_raw_poultry(routine_only=True))
    d["q"] = d["collection_date"].dt.to_period("Q")
    g = d.groupby(["establishment_id", "q"]).agg(n=("positive", "size"), k=("positive", "sum"),
                                                 e=("expected", "sum")).reset_index()
    g = g[g["n"] >= min_samples].sort_values(["establishment_id", "q"])
    g["high"] = (g["k"] >= 2) & (g["k"] >= 2 * g["e"])
    g["next_high"] = g.groupby("establishment_id")["high"].shift(-1)
    g["next_q"] = g.groupby("establishment_id")["q"].shift(-1)
    g = g[(g["next_q"] - g["q"]).apply(lambda x: x.n if pd.notna(x) else 0) == 1]
    return (g.groupby("high")["next_high"].agg(plant_quarters="size", share_high_next="mean")
            .round(3).reset_index())


def category_summary() -> pd.DataFrame:
    """FSIS Salmonella categories by product class, aggregate counts only."""
    c = pd.read_excel(CATEGORY_XLSX, header=3).dropna(subset=["Category"])
    t = pd.crosstab(c["Product Class"], c["Category"].astype(int))
    t.columns = [f"category_{int(x)}" for x in t.columns]
    t["lines"] = t.sum(axis=1)
    t["pct_category_3"] = (100 * t.get("category_3", 0) / t["lines"]).round(1)
    return t.reset_index()


def _plant_status(d: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """FSIS-style category per plant line for one window, from routine samples.
    Category 1 is at or below half the standard, Category 3 is above it."""
    w = d[(d["collection_date"] >= start) & (d["collection_date"] < end)]
    g = (w.groupby(["establishment_id", "product_group"])["positive"]
         .agg(n="size", k="sum").reset_index())
    g = g[(g["n"] >= MIN_PLANT_SAMPLES) & g["product_group"].isin(STANDARD_PCT)].copy()
    std = g["product_group"].map(STANDARD_PCT)
    pct = 100 * g["k"] / g["n"]
    g["status"] = 1 + (pct > std / 2).astype(int) + (pct > std).astype(int)
    return g


def plant_year_pairs() -> pd.DataFrame:
    """Status in one 52-week window joined to the same line's results in the next."""
    d = fsis_raw.load_raw_poultry(routine_only=True)
    year = pd.Timedelta(weeks=52)
    rows = []
    for anchor in map(pd.Timestamp, ANCHORS):
        now = _plant_status(d, anchor - year, anchor)
        now["own_rate"] = (now["k"] + 1) / (now["n"] + 2)
        now = now.drop(columns=["n", "k"])
        nxt = _plant_status(d, anchor, anchor + year).drop(columns="status")
        rows.append(now.merge(nxt, on=["establishment_id", "product_group"]).assign(anchor=anchor))
    return pd.concat(rows, ignore_index=True)


def _cluster_ci(g: pd.DataFrame, reps: int = 2000) -> tuple[float, float]:
    """95% bootstrap interval that resamples plants, since samples within a plant are alike."""
    p = g.groupby("establishment_id")[["k", "n"]].sum().to_numpy()
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(p), (reps, len(p)))
    rates = p[idx, 0].sum(axis=1) / p[idx, 1].sum(axis=1)
    return tuple(100 * np.quantile(rates, [0.025, 0.975]))


def category_forward_rates(pairs: pd.DataFrame) -> pd.DataFrame:
    """Next-year positivity by product and this year's status."""
    rows = []
    for (product, status), g in pairs.groupby(["product_group", "status"]):
        lo, hi = _cluster_ci(g)
        rows.append({"product_group": product, "category": int(status),
                     "plants": g["establishment_id"].nunique(), "line_years": len(g),
                     "samples": int(g["n"].sum()), "positives": int(g["k"].sum()),
                     "pct_positive_next_year": round(100 * g["k"].sum() / g["n"].sum(), 1),
                     "ci_low": round(lo, 1), "ci_high": round(hi, 1),
                     "fsis_standard_pct": STANDARD_PCT[product]})
    return pd.DataFrame(rows)


def _brier(k: pd.Series, n: pd.Series, p: pd.Series) -> float:
    return float((k * (1 - p) ** 2 + (n - k) * p ** 2).sum() / n.sum())


def category_forward_validation(pairs: pd.DataFrame) -> dict:
    """Do rates set on earlier year-pairs beat a product-only rate on the last pair?"""
    last = pairs["anchor"].max()
    train, test = pairs[pairs["anchor"] < last], pairs[pairs["anchor"] == last].copy()

    def rate(keys: list[str]) -> pd.Series:
        s = train.groupby(keys)[["k", "n"]].sum()
        return (s["k"] / s["n"]).rename("p").reset_index()

    prod = test.merge(rate(["product_group"]), on="product_group")
    cat = test.merge(rate(["product_group", "status"]), on=["product_group", "status"])
    a, b = _brier(prod["k"], prod["n"], prod["p"]), _brier(cat["k"], cat["n"], cat["p"])

    def sums(f: pd.DataFrame) -> pd.Series:
        return (f["k"] * (1 - f["p"]) ** 2 + (f["n"] - f["k"]) * f["p"] ** 2).groupby(f["establishment_id"]).sum()

    plants = pd.concat([sums(prod).rename("a"), sums(cat).rename("b")], axis=1).fillna(0).to_numpy()
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(plants), (1000, len(plants)))
    gain = 100 * (1 - plants[idx, 1].sum(axis=1) / plants[idx, 0].sum(axis=1))
    own = {}
    if "own_rate" in test:
        own = {"brier_own_last_year_rate": round(_brier(test["k"], test["n"], test["own_rate"]), 5)}
    return own | {"test_window_start": str(last.date()), "test_samples": int(test["n"].sum()),
            "test_line_years": len(test), "brier_product_only": round(a, 5),
            "brier_product_and_category": round(b, 5),
            "improvement_pct": round(100 * (1 - b / a), 1),
            "improvement_ci": [round(float(x), 1) for x in np.quantile(gain, [0.025, 0.975])]}


def status_agreement() -> pd.DataFrame:
    """How often our rebuilt status equals the category FSIS published, by product."""
    c = pd.read_excel(CATEGORY_XLSX, header=3).dropna(subset=["Category"])
    c["product_group"] = c["Product Class"].map(PRODUCT_CLASSES)
    c = c.assign(key=_plant_key(c["Establishment Number"])).merge(_mpi(), on="key")
    c["establishment_id"] = c["establishment_id"].astype(str)
    d = fsis_raw.load_raw_poultry(routine_only=True)
    d = d.assign(establishment_id=d["establishment_id"].astype(str))
    ours = _plant_status(d, CATEGORY_WINDOW[0], CATEGORY_WINDOW[1] + pd.Timedelta(days=1))
    m = c.merge(ours, on=["establishment_id", "product_group"])
    m["same"] = m["status"] == m["Category"].astype(int)
    return (m.groupby("product_group")["same"].agg(lines="size", share_same="mean")
            .round(3).reset_index())


def _plant_key(number: pd.Series) -> pd.Series:
    """Poultry grant number, stable when other grants on a plant change (M1015+P1015 to P1015)."""
    s = number.astype(str)
    return s.str.extract(r"(P\d+)", expand=False).fillna(s)


def _mpi() -> pd.DataFrame:
    m = pd.read_csv(MPI_CSV, usecols=["establishment_id", "establishment_number"])
    return m.assign(key=_plant_key(m["establishment_number"])).drop_duplicates("key")


def _published(path) -> pd.DataFrame:
    """One FSIS category posting, with the plant ID from the MPI directory."""
    c = pd.read_excel(path, header=3).rename(columns={"EstablishmentNumber": "Establishment Number",
                                                      "ProductClass": "Product Class", "SalmCat": "Category"})
    c = c.dropna(subset=["Category", "Establishment Number"])
    c["product_group"] = c["Product Class"].map(PRODUCT_CLASSES)
    return (c.assign(key=_plant_key(c["Establishment Number"])).merge(_mpi(), on="key")
            .assign(status=lambda x: x["Category"].astype(int))
            [["establishment_id", "product_group", "status"]].dropna())


def published_pairs() -> pd.DataFrame:
    """Published FSIS category joined to the same line's routine results in the 52 weeks after it."""
    d = fsis_raw.load_raw_poultry(routine_only=True)
    rows = []
    for path, end in PUBLISHED_POSTINGS:
        start = pd.Timestamp(end) + pd.Timedelta(days=1)
        w = d[(d["collection_date"] >= start) & (d["collection_date"] < start + pd.Timedelta(weeks=52))]
        g = (w.groupby(["establishment_id", "product_group"])["positive"]
             .agg(n="size", k="sum").reset_index())
        g = g[g["n"] >= MIN_PLANT_SAMPLES]
        rows.append(_published(path).merge(g, on=["establishment_id", "product_group"]).assign(anchor=start))
    return pd.concat(rows, ignore_index=True)


def storm_months() -> pd.DataFrame:
    """Share of past years with a heat, flood or tropical event, by state and month."""
    s = weather.load_storms()
    s = s[s["year"].between(2014, 2025)].copy()
    cols = [c for c in STORM_COLUMNS if c in s.columns]
    s["hit"] = s[cols].sum(axis=1) > 0
    g = s.groupby(["state", "month"])["hit"].sum().reset_index(name="years_with_event")
    g["share_of_years"] = (g["years_with_event"] / 12).round(2)
    return g


def county_need() -> pd.DataFrame:
    """County need score: mean percentile of SVI, low-income low-access share and CDC
    food insecurity. Counties without a PLACES estimate use the other two."""
    svi = ingest_local.load_svi_vulnerability(2022).copy()
    svi["fips"] = svi["FIPS"].astype(str).str.zfill(5)
    svi["people_low_income"] = (svi["population"] * svi["pct_pov150"] / 100).round()
    keep = ["fips", "county", "svi_overall", "people_low_income"]
    a = pd.read_csv(FOOD_ACCESS_CSV, dtype={"fips": str})[["fips", "lila_pop_share"]]
    d = svi.assign(state_abbr=svi["state"])[keep + ["state_abbr"]].merge(a, on="fips", how="left")
    p = pd.read_csv(PLACES_CSV, dtype={"locationid": str})
    p = p[p["data_value_type"] == "Crude prevalence"].rename(
        columns={"locationid": "fips", "data_value": "food_insecure_pct"})[["fips", "food_insecure_pct"]]
    o = pd.read_csv(FOOD_ORGS_CSV, dtype={"county_fips": str}).dropna(subset=["county_fips"])
    o["revenue"] = pd.to_numeric(o["revenue"], errors="coerce").fillna(0)
    orgs = o.sort_values("revenue", ascending=False).groupby("county_fips").agg(
        food_orgs=("ein", "size"), largest_food_org=("name", "first")).reset_index()
    d = d.merge(p, on="fips", how="left").merge(orgs, left_on="fips", right_on="county_fips", how="left")
    d["food_orgs"] = d["food_orgs"].fillna(0).astype(int)
    ranks = d[["svi_overall", "lila_pop_share", "food_insecure_pct"]].rank(pct=True)
    d["need_score"] = ranks.mean(axis=1, skipna=True).where(ranks[["svi_overall", "lila_pop_share"]].notna().all(axis=1)).round(3)
    return d.drop(columns="county_fips").dropna(subset=["need_score", "state_abbr"])


def live_outlook(key: str = "poultry_serotypes") -> pd.DataFrame:
    """Forecast each month with data known 3 months earlier, for the latest
    unobserved months, and apply the alert threshold set on 2022-2023."""
    h = outlook.HORIZON
    sero = outlook.TARGETS[key]
    panel = forecast.build_panel(serotypes=sero, horizon=h)
    hist = panel.dropna(subset=["isolates"] + forecast.M0_FEATURES)
    res, states = forecast.fit(hist, forecast.M0_FEATURES)
    last = hist["period"].max()
    y = panel.set_index(["state", "period"])["isolates"]

    rows = []
    for T in pd.period_range(last + 1, last + h, freq="M"):
        for s in states:
            past = [y.get((s, T - k), np.nan) for k in (h, 12, 24, 36)]
            if any(pd.isna(v) for v in past):
                continue
            rows.append({"state": s, "period": T, "year": T.year, "month": T.month,
                         "log_lag1": np.log1p(past[0]), "log_lag12": np.log1p(past[1]),
                         "trend": (T - forecast.TREND_ORIGIN).n / 12.0, "covid": 0.0,
                         "baseline_3y": sum(past[1:]) / 3})
    live = pd.DataFrame(rows)
    live["expected_cases"] = forecast.predict(res, states, live, forecast.M0_FEATURES)
    sd = np.sqrt(res.scale * live["expected_cases"])
    live["low_80"] = np.clip(live["expected_cases"] - 1.2816 * sd, 0, None)
    live["high_80"] = live["expected_cases"] + 1.2816 * sd
    live["outlook_ratio"] = (live["expected_cases"] + 5) / (live["baseline_3y"] + 5)
    bt = pd.read_csv(outlook.OUT_DIR / "alert_backtest.csv")
    thr = bt[(bt["target"] == key) & (bt["rule"] == "forecast_ratio")]["threshold"].iloc[0]
    live["alert"] = live["outlook_ratio"] >= thr
    keep = ["state", "period", "expected_cases", "low_80", "high_80", "baseline_3y",
            "outlook_ratio", "alert"]
    return live[keep].round(2)


def recall_summary() -> pd.DataFrame:
    """Poultry recalls and alerts per year that name Salmonella."""
    r = pd.read_csv(RECALLS_CSV).fillna("")
    r["year"] = r["field_recall_date"].astype(str).str[:4]
    b = r[r["poultry"] & r["salmonella"]]
    return pd.crosstab(b["year"], b["field_recall_type"]).reset_index()


def outbreak_context() -> tuple[pd.DataFrame, pd.DataFrame]:
    """CDC NORS Salmonella food outbreaks: hospitalization by serotype, and by month."""
    n = pd.read_excel(config.NORS_XLSX)
    genus = [c for c in n.columns if c.startswith("GenusName")]
    f = n[n["PrimaryMode"] == "Food"]
    s = f[f[genus].astype(str).apply(lambda r: r.str.contains("Salmonella").any(), axis=1)].copy()
    sev = s.groupby("SubtypeName_1").agg(outbreaks=("CDCID", "size"), ill=("EstimatedPrimary", "sum"),
                                         hospitalized=("HospitalNum", "sum")).reset_index()
    sev = sev[(sev["outbreaks"] >= 15) & (~sev["SubtypeName_1"].isin(["unknown", "Other"]))]
    sev["pct_hospitalized"] = (100 * sev["hospitalized"] / sev["ill"]).round(1)
    months = s.groupby(s["DateFirstIll"].dt.month).size().rename("outbreaks").reset_index()
    months.columns = ["month", "outbreaks"]
    return (sev.rename(columns={"SubtypeName_1": "serotype"})
            .sort_values("outbreaks", ascending=False), months)


def run() -> None:
    """Write artifacts/context/*."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    product_rates().to_csv(OUT_DIR / "product_rates.csv", index=False)
    plant_persistence().to_csv(OUT_DIR / "plant_persistence.csv", index=False)
    category_summary().to_csv(OUT_DIR / "category_summary.csv", index=False)
    pairs = plant_year_pairs()
    category_forward_rates(pairs).to_csv(OUT_DIR / "category_forward_rates.csv", index=False)
    (OUT_DIR / "category_forward_validation.json").write_text(
        json.dumps(category_forward_validation(pairs), indent=2), encoding="utf-8")
    status_agreement().to_csv(OUT_DIR / "category_status_agreement.csv", index=False)
    published = published_pairs()
    category_forward_rates(published).to_csv(OUT_DIR / "category_published_rates.csv", index=False)
    (OUT_DIR / "category_published_validation.json").write_text(
        json.dumps(category_forward_validation(published), indent=2), encoding="utf-8")
    # FSIS reported samples missing from June-July 2025, so also test without the 2025 posting.
    earlier = published[published["anchor"] < published["anchor"].max()]
    g = earlier[earlier["product_group"] == "Ground chicken"].groupby("status")[["k", "n"]].sum()
    (OUT_DIR / "category_published_robustness.json").write_text(json.dumps(
        category_forward_validation(earlier) | {"ground_chicken_pct_by_category": {
            str(c): round(100 * r.k / r.n, 1) for c, r in g.iterrows()}}, indent=2), encoding="utf-8")
    storm_months().to_csv(OUT_DIR / "storm_months.csv", index=False)
    county_need().to_csv(OUT_DIR / "county_need.csv", index=False)
    live_outlook().to_csv(OUT_DIR / "live_outlook.csv", index=False)
    recall_summary().to_csv(OUT_DIR / "recall_summary.csv", index=False)
    sev, months = outbreak_context()
    sev.to_csv(OUT_DIR / "nors_serotypes.csv", index=False)
    months.to_csv(OUT_DIR / "nors_months.csv", index=False)
    (OUT_DIR / "product_rate_validation.json").write_text(
        json.dumps(product_rate_validation(), indent=2), encoding="utf-8")


__all__ = ["wilson", "product_rates", "product_rate_validation", "plant_persistence",
           "category_summary", "plant_year_pairs", "category_forward_rates",
           "category_forward_validation", "status_agreement", "published_pairs", "storm_months", "county_need", "live_outlook",
           "recall_summary", "outbreak_context", "run"]
