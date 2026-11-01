"""State Salmonella outlook at a realistic lead time, and a backtested alert.

BEAM publishes the prior month late, so a forecast for month T uses data through
T-3 (h=3). This module compares the forecast with fair baselines and picks an
alert threshold on 2022-2023, then reports it on 2024 onward.
"""
from __future__ import annotations

import pandas as pd

from . import beam, config, forecast

OUT_DIR = config.PROJECT_ROOT / "artifacts" / "outlook"
HORIZON = 3
TUNE_END = pd.Period("2023-12", "M")
TOP_SHARE = 0.10
TARGETS = {"poultry_serotypes": beam.POULTRY_SEROTYPES, "enteritidis": ("Enteritidis",),
           "all_salmonella": None}


def _fair_baselines(panel: pd.DataFrame, preds: pd.DataFrame, h: int) -> pd.DataFrame:
    """Add a 3-year same-month mean and a seasonal GLM without lagged counts."""
    out = preds.copy()
    out["climatology_3y"] = out["baseline_3y"]
    glm = ["trend", "covid"]
    data = panel.dropna(subset=["isolates"])
    rows = []
    for T in sorted(out["period"].unique()):
        train = data[data["period"] <= T - h]
        test = data[data["period"] == T]
        res, states = forecast.fit(train, glm)
        rows.append(test[["state", "period"]].assign(
            season_glm=forecast.predict(res, states, test, glm)))
    return out.merge(pd.concat(rows), on=["state", "period"], how="left")


def alert_scores(preds: pd.DataFrame, panel: pd.DataFrame, h: int) -> pd.DataFrame:
    """Candidate alert scores, using only counts known at the forecast origin."""
    p = panel.sort_values(["state", "period"]).copy()

    def rolling(lag: int) -> pd.Series:
        return (p.groupby("state")["isolates"].shift(lag)
                .groupby(p["state"]).rolling(3, min_periods=3).sum()
                .reset_index(level=0, drop=True))

    recent = rolling(h)
    base = (rolling(h + 12) + rolling(h + 24) + rolling(h + 36)) / 3
    p["recent_ratio"] = (recent + 5) / (base + 5)
    out = preds.merge(p[["state", "period", "recent_ratio"]], on=["state", "period"], how="left")
    out["forecast_ratio"] = (out["m0"] + 5) / (out["baseline_3y"] + 5)
    return out


def score_rule(df: pd.DataFrame, score: str, threshold: float) -> dict:
    """Precision, recall and alert volume for score >= threshold."""
    flagged = df[score] >= threshold
    y = df["surge"] == 1
    tp = int((flagged & y).sum())
    return {"rule": score, "threshold": round(float(threshold), 3), "state_months": len(df),
            "alerts": int(flagged.sum()), "alert_rate": round(float(flagged.mean()), 3),
            "surge_rate": round(float(y.mean()), 3),
            "precision": round(tp / max(int(flagged.sum()), 1), 3),
            "recall": round(tp / max(int(y.sum()), 1), 3),
            "false_alarms": int((flagged & ~y).sum())}


def run_target(key: str, serotypes: tuple[str, ...] | None) -> dict:
    """Rolling h=3 validation, baseline comparison and alert backtest for one target."""
    panel = forecast.build_panel(serotypes=serotypes, horizon=HORIZON)
    feats = forecast.m1_features(serotypes)
    val = forecast.rolling_validation(panel, feats, horizon=HORIZON)
    pred = _fair_baselines(panel, val.predictions, HORIZON)
    pred = alert_scores(pred, panel, HORIZON).dropna(subset=["surge", "recent_ratio"])

    rows = [{"target": key, "model": name,
             "MAE": round(float((pred[name] - pred["isolates"]).abs().mean()), 3)}
            for name in ("seasonal_naive", "climatology_3y", "season_glm", "m0", "m1")]
    acc = pd.DataFrame(rows)
    best = acc[acc["model"].isin(["seasonal_naive", "climatology_3y", "season_glm"])]["MAE"].min()
    acc["gain_vs_best_baseline_pct"] = (100 * (1 - acc["MAE"] / best)).round(1)

    tune = pred[pred["period"] <= TUNE_END]
    test = pred[pred["period"] > TUNE_END]
    alerts = []
    for rule in ("recent_ratio", "forecast_ratio"):
        thr = tune[rule].quantile(1 - TOP_SHARE)
        for part, d in (("tune_2022_2023", tune), ("test_2024_on", test)):
            alerts.append({"target": key, "split": part} | score_rule(d, rule, thr))
    by_year = []
    thr = tune["forecast_ratio"].quantile(1 - TOP_SHARE)
    for yr, d in test.groupby(test["period"].dt.year):
        by_year.append({"target": key, "year": int(yr), "months": d["period"].nunique()}
                       | score_rule(d, "forecast_ratio", thr))
    return {"accuracy": acc, "alerts": pd.DataFrame(alerts), "predictions": pred,
            "by_year": pd.DataFrame(by_year)}


def run() -> dict:
    """Run all targets and write artifacts/outlook/*.csv."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    acc, alerts, years = [], [], []
    keep = ["state", "period", "isolates", "m0", "baseline_3y", "surge",
            "recent_ratio", "forecast_ratio"]
    for key, sero in TARGETS.items():
        r = run_target(key, sero)
        acc.append(r["accuracy"])
        alerts.append(r["alerts"])
        years.append(r["by_year"])
        r["predictions"][keep].to_csv(OUT_DIR / f"validation_h3_{key}.csv", index=False)
    a, b = pd.concat(acc), pd.concat(alerts)
    a.to_csv(OUT_DIR / "accuracy_h3.csv", index=False)
    b.to_csv(OUT_DIR / "alert_backtest.csv", index=False)
    pd.concat(years).to_csv(OUT_DIR / "alert_by_year.csv", index=False)
    return {"accuracy": a, "alerts": b}


__all__ = ["HORIZON", "OUT_DIR", "TARGETS", "alert_scores", "score_rule", "run_target", "run"]
