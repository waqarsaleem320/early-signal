"""Step 8 driver — One-month-ahead forecast: base model (M0) vs. updated (M1).

Run from the project root:
    python -m src.step8_forecast

For each target (poultry-associated serotypes = primary, Enteritidis, all
Salmonella) this:
  1. Builds the state-month panel: CDC BEAM human isolates + lagged FSIS
     routine raw-poultry positivity, NOAA climate anomalies, NOAA storms.
  2. Runs rolling-origin validation (refit before every test month,
     2022-01 onward) for seasonal-naive, persistence, M0 and M1.
  3. Tests whether M1 beats M0, per state-month and summed nationally
     (bootstrap CI over test months).
  4. Fits M1 on all complete months: rate ratios with 95% CI.
  5. Forecasts the next month with the excess (M1 - M0) per state.
  6. Repeats the M1 test with a 1-month FSIS lag (best case).

Outputs: artifacts/forecast/*.csv + as_of.json, artifacts/figures/step8_*.png.
"""
from __future__ import annotations

import json
import sys

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import beam, config, forecast  # noqa: E402

ARTIFACT_DIR = config.PROJECT_ROOT / "artifacts" / "forecast"
FIG_DIR = config.PROJECT_ROOT / "artifacts" / "figures"
TARGETS: dict[str, tuple[str, ...] | None] = {
    "poultry_serotypes": beam.POULTRY_SEROTYPES,
    "enteritidis": ("Enteritidis",),
    "all_salmonella": None,
}
TARGET_LABELS = {
    "poultry_serotypes": "Poultry-associated serotypes",
    "enteritidis": "Enteritidis",
    "all_salmonella": "All Salmonella",
}


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def _plot_national(nat: pd.DataFrame, label: str, path) -> None:
    fig, ax = plt.subplots(figsize=(9, 3.8))
    x = nat.index.to_timestamp()
    ax.plot(x, nat["isolates"], color="#111", lw=2, label="Actual (BEAM)")
    ax.plot(x, nat["seasonal_naive"], color="#9aa3ad", lw=1.2, ls="--", label="Seasonal naive")
    ax.plot(x, nat["m0"], color="#2f6db5", lw=1.6, label="M0 (base)")
    ax.plot(x, nat["m1"], color="#d9822b", lw=1.6, label="M1 (updated)")
    ax.set_title(f"{label}: national monthly human isolates, 1-month-ahead forecasts")
    ax.set_ylabel("Isolates")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=4, fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)  # save only; keeps notebooks that %run this from showing duplicates


def _plot_coefficients(coef: pd.DataFrame, label: str, path) -> None:
    c = coef.drop(index=[f for f in forecast.M0_FEATURES if f in coef.index])
    fig, ax = plt.subplots(figsize=(8, 0.5 * len(c) + 1.2))
    y = np.arange(len(c))[::-1]
    ax.errorbar(c["rate_ratio"], y, xerr=[c["rate_ratio"] - c["ci_low"], c["ci_high"] - c["rate_ratio"]],
                fmt="o", color="#2f6db5", ecolor="#9aa3ad", capsize=3)
    ax.axvline(1, color="#888", ls=":")
    ax.set_yticks(y, c["label"], fontsize=8)
    ax.set_xlabel("Rate ratio per unit change (95% CI)")
    ax.set_title(f"{label}: current signals in M1 (full-data fit)")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def run() -> int:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    summary, as_of = [], {}

    for key, sero in TARGETS.items():
        label = TARGET_LABELS[key]
        feats1 = forecast.m1_features(sero)
        section(f"{label}: panel")
        panel = forecast.build_panel(serotypes=sero, include_next=True)
        hist = panel.dropna(subset=["isolates"])
        as_of = panel.attrs["as_of"] | {"next_period": panel.attrs["next_period"]}
        print(f"   state-months : {len(hist):,}  ({hist['period'].min()} to {hist['period'].max()})")
        print(f"   data as of   : {as_of}")

        section(f"{label}: rolling-origin validation")
        val = forecast.rolling_validation(hist, feats1)
        print(val.metrics.to_string())
        state_imp = forecast.paired_improvement(val.predictions)
        nat = forecast.national_check(val.predictions)
        print(f"   M1 vs M0, state-month MAE reduction: {state_imp['mae_reduction']:.3f} "
              f"(95% CI {state_imp['ci_low']:.3f} to {state_imp['ci_high']:.3f})")
        print(f"   M1 vs M0, national: {nat['m1_gain_pct']:.1f}% "
              f"(95% CI {nat['gain_ci_low_pct']:.1f} to {nat['gain_ci_high_pct']:.1f})")
        val.predictions.to_csv(ARTIFACT_DIR / f"validation_{key}.csv", index=False)
        nat["national"].to_csv(ARTIFACT_DIR / f"validation_national_{key}.csv")
        _plot_national(nat["national"], label, FIG_DIR / f"step8_national_{key}.png")

        section(f"{label}: M1 coefficients (all complete months)")
        coef = forecast.coefficient_table(hist, feats1)
        print(coef[["label", "rate_ratio", "ci_low", "ci_high", "p_value"]].to_string())
        coef.to_csv(ARTIFACT_DIR / f"coefficients_{key}.csv")
        _plot_coefficients(coef, label, FIG_DIR / f"step8_coefficients_{key}.png")

        section(f"{label}: next-month forecast ({panel.attrs['next_period']})")
        nxt = forecast.next_month_forecast(panel, feats1)
        print(nxt[["state", "m0", "m1", "excess_pct", "excess_z", "priority"]].head(8).round(2).to_string())
        nxt.to_csv(ARTIFACT_DIR / f"next_month_{key}.csv", index=False)

        section(f"{label}: sensitivity — FSIS lag 1 month (best case)")
        hist3 = forecast.build_panel(serotypes=sero, fsis_lag=1)
        val3 = forecast.rolling_validation(hist3, feats1)
        imp3 = forecast.paired_improvement(val3.predictions)
        print(f"   M1 vs M0 (lag 1): {val3.metrics.loc['m1', 'skill_vs_m0_%']:.2f}% "
              f"(MAE reduction CI {imp3['ci_low']:.3f} to {imp3['ci_high']:.3f})")

        m = val.metrics
        summary.append({
            "target": label, "test_months": val.predictions["period"].nunique(),
            "mae_seasonal": m.loc["seasonal_naive", "MAE"], "mae_persistence": m.loc["persistence", "MAE"],
            "mae_m0": m.loc["m0", "MAE"], "mae_m1": m.loc["m1", "MAE"],
            "m0_skill_vs_seasonal_pct": m.loc["m0", "skill_vs_seasonal_%"],
            "m1_vs_m0_pct": m.loc["m1", "skill_vs_m0_%"],
            "m1_vs_m0_ci": f"{state_imp['ci_low']:.3f} to {state_imp['ci_high']:.3f}",
            "national_m1_gain_pct": round(nat["m1_gain_pct"], 2),
            "national_gain_ci_pct": f"{nat['gain_ci_low_pct']:.1f} to {nat['gain_ci_high_pct']:.1f}",
            "m1_vs_m0_pct_fsis_lag1": val3.metrics.loc["m1", "skill_vs_m0_%"],
        })

    section("Summary")
    summ = pd.DataFrame(summary)
    print(summ.to_string(index=False))
    summ.to_csv(ARTIFACT_DIR / "summary.csv", index=False)
    (ARTIFACT_DIR / "as_of.json").write_text(json.dumps(as_of, indent=2))
    print(f"\nArtifacts: {ARTIFACT_DIR}\nFigures:   {FIG_DIR}/step8_*.png")
    return 0


if __name__ == "__main__":
    sys.exit(run())
