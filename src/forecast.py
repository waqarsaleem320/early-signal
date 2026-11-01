"""One-month-ahead Salmonella forecast: base model (M0) vs. updated model (M1).

Target   : human Salmonella isolates per (state, month), CDC BEAM, 2018 onward.
M0 (base): what history alone expects — state level, calendar-month
           seasonality, long-term trend, last month's and last year's counts,
           COVID period.
M1       : M0 + current signals from month t-1 —
             * FSIS routine raw-poultry positivity (national and state O/E),
             * NOAA temperature and precipitation anomalies,
             * NOAA storm events (heat, flood/tropical, damage).
Excess   : M1 vs. M0. Where M1 expects more cases than M0, current conditions
           push risk above what is normal for that state and month; a negative
           excess supports keeping product flowing (food-security side).

Validation (rolling origin from 2022-01): M1 does not improve on M0, so the
excess is context, not an alarm. See src/outlook.py for the realistic 3-month
horizon and fair baselines. Run `python run_all.py` to regenerate results.

Timing: h=1 assumes last month's BEAM count is already final, so treat it as a
best case. Validation uses the latest data vintage, so it is a retrospective
test, not a real-time one. Models are refit on months before each forecast origin.

Both models are quasi-Poisson GLMs (Poisson mean, dispersion estimated), so
coefficients are interpretable as rate ratios with confidence intervals.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm

from . import beam, fsis_raw, weather

KEYS = ["state", "year", "month"]
COVID_START, COVID_END = pd.Period("2020-03", "M"), pd.Period("2021-06", "M")

M0_FEATURES = ["log_lag1", "log_lag12", "trend", "covid"]
TREND_ORIGIN = pd.Period("2018-01", "M")
# One national FSIS input per target (the two national measures are collinear):
# product-mix-adjusted O/E for all Salmonella, serotype-matched positivity when
# the target is a serotype group.
_M1_COMMON = ["fsis_state_oe", "tmax_anom", "precip_anom",
              "log_storm_heat", "log_storm_flood", "log_storm_damage"]
FSIS_LAG_MONTHS = 3  # the public FSIS file lags about 3-4 months


FOOD_FEATURES = ["log_food_state", "food_nat_ratio"]
SURGE_RATIO, SURGE_MIN_EXCESS = 1.3, 5.0   # surge: >=30% and >=5 cases above 3-year same-month mean


def m1_features(serotypes: tuple[str, ...] | None = None, food: bool = False) -> list[str]:
    """M0 features plus current signals; national FSIS input matched to target.
    food=True adds BEAM food/animal/environment isolates (state and national)."""
    feats = M0_FEATURES + ["fsis_nat_sero" if serotypes else "fsis_nat_oe"] + _M1_COMMON
    return feats + FOOD_FEATURES if food else feats
FEATURE_LABELS = {
    "log_lag1": "Cases last month (log)",
    "log_lag12": "Cases same month last year (log)",
    "trend": "Long-term trend (per year since 2018)",
    "covid": "COVID period (Mar 2020–Jun 2021)",
    "fsis_nat_oe": "FSIS national raw-poultry O/E, last month",
    "fsis_nat_sero": "FSIS national positivity for the target serotypes (ratio to mean), last month",
    "fsis_state_oe": "FSIS state raw-poultry O/E, last 3 months (shrunk)",
    "tmax_anom": "Max-temperature anomaly last month (°F)",
    "precip_anom": "Precipitation anomaly last month (in)",
    "log_storm_heat": "Heat events last month (log)",
    "log_storm_flood": "Flood/tropical events last month (log)",
    "log_storm_damage": "Storm damage last month (log $M)",
    "log_food_state": "Food/animal Salmonella isolates in the state, last month (log)",
    "food_nat_ratio": "National food/animal isolates for the target serotypes (ratio to mean), last month",
}
STATE_OE_SHRINK = 10.0   # pseudo-count pulling small-sample states toward 1.0


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------
def _period(df: pd.DataFrame) -> pd.PeriodIndex:
    return pd.PeriodIndex.from_fields(year=df["year"], month=df["month"], freq="M")


def fsis_features(serotypes: tuple[str, ...] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """National monthly O/E and state 3-month shrunk O/E from routine sampling,
    plus national positivity of the target serotypes relative to its mean
    (fsis_nat_sero; equals overall positivity when no serotypes are given).

    Expected positives use each product group's positivity over the whole
    routine record, so O/E tracks change over time and place, not product mix.
    """
    d = fsis_raw.add_expected(fsis_raw.load_raw_poultry(routine_only=True))
    d["year"], d["month"] = d["collection_date"].dt.year, d["collection_date"].dt.month

    nat = d.groupby(["year", "month"]).agg(o=("positive", "sum"), e=("expected", "sum"))
    nat["fsis_nat_oe"] = nat["o"] / nat["e"]
    hit = (d["salmonella_serotype"].isin(serotypes).fillna(False) if serotypes
           else d["positive"]).astype(float)
    sero = hit.groupby([d["year"], d["month"]]).mean()
    nat["fsis_nat_sero"] = sero / sero.mean()
    nat = nat[["fsis_nat_oe", "fsis_nat_sero"]].reset_index()

    st = d.groupby(KEYS).agg(o=("positive", "sum"), e=("expected", "sum")).reset_index()
    st["period"] = _period(st)
    full = pd.MultiIndex.from_product(
        [st["state"].unique(), pd.period_range(st["period"].min(), st["period"].max(), freq="M")],
        names=["state", "period"]).to_frame(index=False)
    st = full.merge(st.drop(columns=["year", "month"]), on=["state", "period"], how="left").fillna(0)
    st = st.sort_values(["state", "period"])
    roll = st.groupby("state")[["o", "e"]].transform(lambda x: x.rolling(3, min_periods=1).sum())
    st["fsis_state_oe"] = (roll["o"] + STATE_OE_SHRINK) / (roll["e"] + STATE_OE_SHRINK)
    st["year"], st["month"] = st["period"].dt.year, st["period"].dt.month
    return nat, st[KEYS + ["fsis_state_oe"]]


def build_panel(serotypes: tuple[str, ...] | None = None,
                fsis_lag: int = FSIS_LAG_MONTHS, include_next: bool = False,
                horizon: int = 1) -> pd.DataFrame:
    """State-month panel: target, lagged target, and earlier-month covariates.

    horizon h = months ahead: the latest known cases ("log_lag1"), weather,
    storms and food isolates come from month t-h; FSIS from t-max(h, fsis_lag).
    With h=1 (default): weather/storms from t-1, FSIS from t-fsis_lag.
    Also adds baseline_3y (mean of the same month in the 3 previous years) and
    surge (cases >= 30% and >= 5 above baseline_3y) for surge scoring.
    With include_next=True, one extra row per state is added for the month
    after the last complete month (isolates = NaN): the live forecast rows.
    If a source has not yet published the month a live row needs, its latest
    available month is used and recorded in panel.attrs["as_of"].
    """
    y = beam.human_isolates(serotypes=serotypes)
    last = beam.complete_through(y)
    y = y[_period(y) <= last].copy()
    y["period"] = _period(y)
    nxt = last + 1
    if include_next:
        extra = pd.DataFrame({"state": y["state"].unique(), "period": nxt,
                              "year": nxt.year, "month": nxt.month, "isolates": np.nan})
        y = pd.concat([y, extra], ignore_index=True)
    y = y.sort_values(["state", "period"])
    g = y.groupby("state")["isolates"]
    y["log_lag1"] = np.log1p(g.shift(horizon))      # latest month known at forecast time
    y["log_lag12"] = np.log1p(g.shift(12))
    y["baseline_3y"] = (g.shift(12) + g.shift(24) + g.shift(36)) / 3
    y["surge"] = ((y["isolates"] >= SURGE_RATIO * y["baseline_3y"])
                  & (y["isolates"] - y["baseline_3y"] >= SURGE_MIN_EXCESS)).astype(float)
    y.loc[y["baseline_3y"].isna() | y["isolates"].isna(), "surge"] = np.nan
    y["covid"] = ((y["period"] >= COVID_START) & (y["period"] <= COVID_END)).astype(float)
    y["trend"] = (y["period"] - TREND_ORIGIN).apply(lambda d: d.n) / 12.0

    # Covariates observed in month t-1, joined onto target month t.
    nat, st = fsis_features(serotypes)
    clim = weather.load_climate()[KEYS + ["tmax_anom", "precip_anom"]]
    storms = weather.load_storms()
    storms = storms.assign(
        log_storm_heat=np.log1p(storms["storm_heat"]),
        log_storm_flood=np.log1p(storms["storm_flood"] + storms["storm_tropical"]),
        log_storm_damage=np.log1p(storms["storm_damage_musd"]),
    )[KEYS + ["log_storm_heat", "log_storm_flood", "log_storm_damage"]]
    food = beam.nonhuman_isolates(serotypes=serotypes)
    food_nat = food.groupby(["year", "month"])["nonhuman_isolates"].sum().rename("food_nat").reset_index()
    food_nat["food_nat_ratio"] = food_nat["food_nat"] / food_nat["food_nat"].mean()
    food_state = food.assign(log_food_state=np.log1p(food["nonhuman_isolates"]))[KEYS + ["log_food_state"]]

    lag_keys = {"year": "prev_year", "month": "prev_month"}
    for lag, covs in ((max(fsis_lag, horizon), (nat, st)),
                      (horizon, (clim, storms, food_nat[["year", "month", "food_nat_ratio"]], food_state))):
        prev = y["period"] - lag
        y["prev_year"], y["prev_month"] = prev.dt.year, prev.dt.month
        for cov in covs:
            on = ["prev_year", "prev_month"] + (["state"] if "state" in cov.columns else [])
            y = y.merge(cov.rename(columns=lag_keys), on=on, how="left")

    as_of = {
        "beam_complete_through": str(last),
        "fsis": str(pd.Period(year=int(nat["year"].iloc[-1]), month=int(nat["month"].iloc[-1]), freq="M")),
        "climate": str(clim.dropna().pipe(lambda c: _period(c).max())),
        "storms": str(_period(storms).max()),
    }
    if include_next:
        live = y["period"] == nxt
        # Sources not yet published for the month the live row needs: carry the
        # latest available value forward (stated in attrs["as_of"]).
        y = y.sort_values(["state", "period"])
        for c in ("fsis_nat_oe", "fsis_nat_sero", "fsis_state_oe", "tmax_anom", "precip_anom"):
            filled = y.groupby("state")[c].ffill()
            y.loc[live, c] = filled[live]
        storm_missing = _period(storms).max() < (nxt - 1)
        if storm_missing:
            for c in ("log_storm_heat", "log_storm_flood", "log_storm_damage"):
                y.loc[live, c] = np.nan   # filled with 0 below; flagged in as_of
            as_of["storms_note"] = "storm month not yet published; treated as no events"

    y["log_food_state"] = y["log_food_state"].fillna(0.0)  # no isolates reported
    y["fsis_state_oe"] = y["fsis_state_oe"].fillna(1.0)   # no plants sampled -> neutral
    for c in ("log_storm_heat", "log_storm_flood", "log_storm_damage"):
        y[c] = y[c].fillna(0.0)                            # no events reported
    out = y.drop(columns=["prev_year", "prev_month"]).reset_index(drop=True)
    out.attrs["as_of"] = as_of
    out.attrs["next_period"] = str(nxt)
    out.attrs["horizon"] = horizon
    return out


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
def _design(df: pd.DataFrame, features: list[str], states: list[str]) -> pd.DataFrame:
    X = df[features].astype(float).copy()
    for s in states[1:]:
        X[f"st_{s}"] = (df["state"] == s).astype(float)
    for m in range(2, 13):
        X[f"m_{m}"] = (df["month"] == m).astype(float)
    return sm.add_constant(X, has_constant="add")


def fit(train: pd.DataFrame, features: list[str]):
    states = sorted(train["state"].unique())
    X = _design(train, features, states)
    res = sm.GLM(train["isolates"], X, family=sm.families.Poisson()).fit(scale="X2")
    return res, states


def predict(res, states: list[str], df: pd.DataFrame, features: list[str]) -> np.ndarray:
    X = _design(df, features, states)
    return np.asarray(res.predict(X[res.model.exog_names]))


@dataclass
class ValidationResult:
    predictions: pd.DataFrame     # per state-month: actual, baselines, M0, M1, excess
    metrics: pd.DataFrame         # per model: MAE, RMSE, skill vs seasonal naive
    excess_check: pd.DataFrame    # does flagged excess come true?


def rolling_validation(panel: pd.DataFrame, feats1: list[str],
                       first_test: str = "2022-01", horizon: int | None = None,
                       extra_sets: dict[str, list[str]] | None = None) -> ValidationResult:
    """Refit M0 and M1 on months known at the forecast origin; predict the test month.

    With horizon h, a forecast for month T is made at the end of month T-h, so
    training uses target months <= T-h only. extra_sets adds further models
    (name -> feature list), scored alongside M0 and M1.
    """
    h = horizon or panel.attrs.get("horizon", 1)
    extra_sets = extra_sets or {}
    needed = sorted(set(feats1).union(*extra_sets.values()) if extra_sets else set(feats1))
    data = panel.dropna(subset=needed + ["isolates"]).copy()
    out = []
    for T in pd.period_range(pd.Period(first_test, "M"), data["period"].max(), freq="M"):
        train, test = data[data["period"] <= T - h], data[data["period"] == T]
        if test.empty:
            continue
        r0, s0 = fit(train, M0_FEATURES)
        r1, s1 = fit(train, feats1)
        t = test[["state", "period", "year", "month", "isolates", "baseline_3y", "surge"]].copy()
        for name, feats in extra_sets.items():
            rx, sx = fit(train, feats)
            t[name] = predict(rx, sx, test, feats)
        t["seasonal_naive"] = np.expm1(test["log_lag12"])
        t["persistence"] = np.expm1(test["log_lag1"])
        t["m0"] = predict(r0, s0, test, M0_FEATURES)
        t["m1"] = predict(r1, s1, test, feats1)
        t["dispersion"] = r1.scale
        out.append(t)
    pred = pd.concat(out, ignore_index=True)
    pred["excess"] = pred["m1"] - pred["m0"]
    pred["excess_pct"] = 100 * pred["excess"] / pred["m0"]
    # Excess in units of the expected noise around M0 (quasi-Poisson SD).
    pred["excess_z"] = pred["excess"] / np.sqrt(pred["dispersion"] * pred["m0"])

    rows = []
    for name in ("seasonal_naive", "persistence", "m0", "m1", *extra_sets):
        err = pred[name] - pred["isolates"]
        rows.append({"model": name, "MAE": err.abs().mean(),
                     "RMSE": np.sqrt((err ** 2).mean())})
    metrics = pd.DataFrame(rows).set_index("model")
    metrics["skill_vs_seasonal_%"] = 100 * (1 - metrics["MAE"] / metrics.loc["seasonal_naive", "MAE"])
    metrics["skill_vs_m0_%"] = 100 * (1 - metrics["MAE"] / metrics.loc["m0", "MAE"])

    # Validation of the excess signal: when M1 says "above normal", is it?
    pred["actual_vs_m0"] = pred["isolates"] - pred["m0"]
    bins = pd.cut(pred["excess_z"], [-np.inf, -1.645, -0.5, 0.5, 1.645, np.inf],
                  labels=["well below", "below", "near normal", "above", "well above"])
    check = pred.groupby(bins, observed=True).agg(
        state_months=("isolates", "size"),
        mean_predicted_excess_pct=("excess_pct", "mean"),
        mean_actual_vs_m0_pct=("actual_vs_m0", lambda x: 100 * x.sum() / pred.loc[x.index, "m0"].sum()),
        share_actual_above_m0=("actual_vs_m0", lambda x: (x > 0).mean()),
    )
    return ValidationResult(pred, metrics.round(2), check.round(3))


def paired_improvement(pred: pd.DataFrame, a: str = "m0", b: str = "m1",
                       n_boot: int = 2000, seed: int = 0) -> dict:
    """Bootstrap (by test month) CI for MAE(a) - MAE(b); > 0 means b is better."""
    rng = np.random.default_rng(seed)
    per_month = pred.assign(da=(pred[a] - pred["isolates"]).abs(),
                            db=(pred[b] - pred["isolates"]).abs()) \
                    .groupby("period")[["da", "db"]].mean()
    diff = (per_month["da"] - per_month["db"]).to_numpy()
    boots = [rng.choice(diff, size=len(diff), replace=True).mean() for _ in range(n_boot)]
    return {"mae_reduction": float(diff.mean()),
            "ci_low": float(np.percentile(boots, 2.5)),
            "ci_high": float(np.percentile(boots, 97.5)),
            "months_b_better": float((diff > 0).mean())}


def coefficient_table(panel: pd.DataFrame, feats1: list[str]) -> pd.DataFrame:
    """M1 fit on all complete months: rate ratio per unit change, with 95% CI."""
    data = panel.dropna(subset=feats1)
    res, _ = fit(data, feats1)
    ci = res.conf_int()
    tbl = pd.DataFrame({
        "feature": feats1,
        "label": [FEATURE_LABELS[f] for f in feats1],
        "rate_ratio": np.exp(res.params[feats1]),
        "ci_low": np.exp(ci.loc[feats1, 0]),
        "ci_high": np.exp(ci.loc[feats1, 1]),
        "p_value": res.pvalues[feats1],
    }).set_index("feature")
    return tbl.round(4)



def surge_scores(pred: pd.DataFrame, models: list[str], top_frac: float = 0.10,
                 ratio: float = SURGE_RATIO, min_excess: float = SURGE_MIN_EXCESS) -> pd.DataFrame:
    """How well each model's forecast picks out surge state-months.

    Surge = actual cases >= ratio x and >= min_excess above the 3-year
    same-month baseline (model-independent). Score = forecast / baseline (what
    the model expects relative to normal). AUC = chance a random surge month is
    ranked above a random non-surge month (0.5 = no skill). Precision/recall are
    for flagging the top `top_frac` of state-months by score.
    """
    d = pred.dropna(subset=["baseline_3y", "isolates"])
    d = d[d["baseline_3y"] > 0]
    y = ((d["isolates"] >= ratio * d["baseline_3y"])
         & (d["isolates"] - d["baseline_3y"] >= min_excess)).to_numpy()
    rows = []
    for name in models:
        score = (d[name] / d["baseline_3y"]).to_numpy()
        ranks = pd.Series(score).rank().to_numpy()
        n1, n0 = y.sum(), (~y).sum()
        auc = (ranks[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0) if n1 and n0 else np.nan
        k = max(1, int(round(top_frac * len(d))))
        flagged = np.zeros(len(d), dtype=bool)
        flagged[np.argsort(-score)[:k]] = True
        rows.append({"model": name, "surge_auc": auc,
                     "precision_top10": (y & flagged).sum() / k,
                     "recall_top10": (y & flagged).sum() / n1 if n1 else np.nan})
    out = pd.DataFrame(rows).set_index("model")
    out.attrs["surge_rate"] = float(y.mean())
    return out.round(3)


def next_month_forecast(panel: pd.DataFrame, feats1: list[str],
                        z_flag: float = 1.645) -> pd.DataFrame:
    """Fit M0/M1 on all complete months and forecast the live (next) month.

    Returns one row per state with both forecasts, an 80% interval for M1,
    the excess (M1 - M0) in cases, %, and noise units, and a priority label:
      excess_z >=  z_flag : "Above normal"  -> act first
      excess_z <= -z_flag : "Below normal"  -> keep product flowing
      otherwise           : "Near normal"   -> routine
    """
    hist = panel.dropna(subset=["isolates"] + feats1)
    live = panel[panel["isolates"].isna()].dropna(subset=feats1)
    r0, s0 = fit(hist, M0_FEATURES)
    r1, s1 = fit(hist, feats1)
    out = live[["state", "period"]].copy()
    out["m0"] = predict(r0, s0, live, M0_FEATURES)
    out["m1"] = predict(r1, s1, live, feats1)
    sd = np.sqrt(r1.scale * out["m1"])
    out["m1_low80"] = np.clip(out["m1"] - 1.2816 * sd, 0, None)
    out["m1_high80"] = out["m1"] + 1.2816 * sd
    out["excess"] = out["m1"] - out["m0"]
    out["excess_pct"] = 100 * out["excess"] / out["m0"]
    out["excess_z"] = out["excess"] / np.sqrt(r1.scale * out["m0"])
    out["priority"] = np.select([out["excess_z"] >= z_flag, out["excess_z"] <= -z_flag],
                                ["Above normal", "Below normal"], "Near normal")
    # Contribution of each current signal to log(M1): coefficient x value.
    extra = [f for f in feats1 if f not in M0_FEATURES]
    for f in extra:
        out[f"contrib_{f}"] = r1.params[f] * live[f].to_numpy()
    out[extra] = live[extra].to_numpy()
    return out.sort_values("excess_z", ascending=False).reset_index(drop=True)


def national_check(pred: pd.DataFrame, n_boot: int = 2000, seed: int = 0) -> dict:
    """Sum state forecasts to national monthly totals and compare M0 vs M1."""
    n = pred.groupby("period")[["isolates", "seasonal_naive", "m0", "m1"]].sum()
    mae = {c: float((n[c] - n["isolates"]).abs().mean()) for c in ("seasonal_naive", "m0", "m1")}
    d = ((n["m0"] - n["isolates"]).abs() - (n["m1"] - n["isolates"]).abs()).to_numpy()
    rng = np.random.default_rng(seed)
    boots = [rng.choice(d, size=len(d), replace=True).mean() for _ in range(n_boot)]
    return {"mae_seasonal": mae["seasonal_naive"], "mae_m0": mae["m0"], "mae_m1": mae["m1"],
            "m1_gain_pct": 100 * (1 - mae["m1"] / mae["m0"]),
            "gain_ci_low_pct": 100 * float(np.percentile(boots, 2.5)) / mae["m0"],
            "gain_ci_high_pct": 100 * float(np.percentile(boots, 97.5)) / mae["m0"],
            "national": n}


__all__ = ["M0_FEATURES", "FSIS_LAG_MONTHS", "FEATURE_LABELS", "m1_features", "build_panel",
           "fit", "predict", "next_month_forecast", "national_check", "surge_scores",
           "FOOD_FEATURES",
           "rolling_validation", "paired_improvement", "coefficient_table", "ValidationResult"]
