"""Draw the report figures from artifacts/ with SciencePlots. Run after run_all.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scienceplots  # noqa: F401
from scipy.stats import spearmanr

matplotlib.use("Agg")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import context  # noqa: E402
from src.decision import actions as A  # noqa: E402

CTX, OUT = ROOT / "artifacts" / "context", ROOT / "artifacts" / "outlook"
FIG = ROOT / "report" / "figures"
CAT = {1: "#1F7A5C", 2: "#C98A00", 3: "#A8261B"}
INK, BLUE, GREY = "#12343B", "#2B7A9E", "#8FA3A9"


def save(fig: plt.Figure, name: str) -> None:
    fig.savefig(FIG / f"{name}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


def categories() -> None:
    """Next-year positivity by published category, with plant-resampled intervals."""
    d = pd.read_csv(CTX / "category_published_rates.csv")
    groups = ["Ground chicken", "Ground turkey", "Chicken parts", "Chicken carcass"]
    fig, axes = plt.subplots(1, 4, figsize=(6.7, 2.5), sharey=True)
    for ax, g in zip(axes, groups):
        r = d[d["product_group"] == g].sort_values("category")
        v = r["pct_positive_next_year"].to_numpy()
        err = [v - r["ci_low"].to_numpy(), r["ci_high"].to_numpy() - v]
        ax.bar(r["category"], v, yerr=err, width=.68, color=[CAT[c] for c in r["category"]],
               error_kw=dict(ecolor=INK, lw=.8, capsize=2))
        ax.axhline(r["fsis_standard_pct"].iloc[0], color=INK, ls=":", lw=1)
        for c, x, hi in zip(r["category"], v, r["ci_high"]):
            ax.text(c, hi + 1.5, f"{x:.1f}", ha="center", fontsize=7)
        ax.set_title(g, fontsize=8.5)
        ax.set_xticks([1, 2, 3], ["Cat 1", "Cat 2", "Cat 3"])
        ax.tick_params(axis="x", which="minor", bottom=False, top=False)
        ax.set_xlim(.4, 3.6)
    axes[0].set_ylabel("Positive next year (\\%)".replace("\\", ""))
    axes[0].set_ylim(0, 68)
    save(fig, "fig1_category_forward")


def by_year() -> None:
    """The same test in each posting year."""
    p = context.published_pairs()
    p = p[p["product_group"].isin(["Ground chicken", "Chicken parts"])]
    g = p.groupby(["product_group", "anchor", "status"])[["k", "n"]].sum().reset_index()
    g["pct"] = 100 * g["k"] / g["n"]
    g.to_csv(CTX / "category_published_by_year.csv", index=False)
    fig, axes = plt.subplots(1, 2, figsize=(6.2, 2.4), sharey=True)
    for ax, name in zip(axes, ["Ground chicken", "Chicken parts"]):
        for c, mark in zip((3, 2, 1), ("s", "^", "o")):
            r = g[(g["product_group"] == name) & (g["status"] == c)]
            ax.plot(r["anchor"].dt.year + 1, r["pct"], marker=mark, color=CAT[c], label=f"Category {c}", lw=1.3, ms=4)
        ax.set_title(name, fontsize=9)
        ax.set_xlabel("Year ending the scoring window")
        ax.set_xticks([2023, 2024, 2025, 2026])
        ax.tick_params(axis="x", which="minor", bottom=False, top=False)
    axes[0].set_ylabel("Positive next year (%)")
    axes[0].set_ylim(0, 62)
    axes[0].legend(frameon=False, fontsize=7)
    save(fig, "fig2_by_year")


def forecast() -> None:
    """Three-month forecast error against fair baselines."""
    a = pd.read_csv(OUT / "accuracy_h3.csv")
    names = {"seasonal_naive": "Same month", "climatology_3y": "3-year mean", "season_glm": "Seasonal GLM",
             "m0": "History model", "m1": "Plus FSIS, weather"}
    fig, axes = plt.subplots(1, 3, figsize=(6.7, 2.4))
    titles = {"poultry_serotypes": "Poultry serotypes", "enteritidis": "Enteritidis", "all_salmonella": "All Salmonella"}
    for ax, (t, title) in zip(axes, titles.items()):
        r = a[a["target"] == t].set_index("model").loc[list(names)]
        ax.barh(list(names.values())[::-1], r["MAE"][::-1],
                color=[GREY, BLUE, GREY, GREY, GREY], height=.66)
        ax.set_title(title, fontsize=8.5)
        ax.set_xlabel("MAE, isolates per state-month")
        ax.tick_params(axis="y", which="both", left=False, right=False)
        ax.tick_params(axis="x", which="both", top=False)
    for ax in axes[1:]:
        ax.set_yticklabels([])
    save(fig, "fig3_forecast")


def alert() -> None:
    """State alert precision by year."""
    y = pd.read_csv(OUT / "alert_by_year.csv")
    y = y[y["target"] == "poultry_serotypes"]
    fig, ax = plt.subplots(figsize=(3.3, 2.3))
    x = np.arange(len(y))
    ax.bar(x - .19, 100 * y["precision"], .36, color=BLUE, label="Alert precision")
    ax.bar(x + .19, 100 * y["surge_rate"], .36, color=GREY, label="Base rate")
    ax.set_xticks(x, y["year"])
    ax.tick_params(axis="x", which="minor", bottom=False, top=False)
    ax.set_ylabel("Percent")
    ax.set_ylim(0, 85)
    ax.legend(frameon=False, fontsize=7)
    save(fig, "fig4_alert")


def tradeoff() -> None:
    """Scenario 1: exposure and food on one chart."""
    inp = A.load_inputs()
    s = A.Situation("MO", 7, "Ground chicken", 10_000, fsis_category=3, has_cooked_line=True)
    t = A.compare_actions(s, inp)
    labels = ["Release raw", "Add verification", "Hold and test", "Redirect to cook", "Redirect, donate 25%", "Discard or render"]
    fig, axes = plt.subplots(1, 2, figsize=(6.2, 2.4), sharey=True)
    y = np.arange(len(t))[::-1]
    axes[0].barh(y, t["exposure_index"], color=BLUE, height=.62)
    axes[0].set_yticks(y, labels)
    axes[0].set_xlabel("Exposure index (parts sold raw = 1)")
    axes[1].barh(y + .17, t["servings_kept"] / 1000, color=GREY, height=.32, label="Servings kept")
    axes[1].barh(y - .17, t["servings_to_need"] / 1000, color=CAT[1], height=.32, label="To high-need counties")
    axes[1].set_xlabel("Thousand 3-oz servings")
    axes[1].legend(frameon=False, fontsize=7, loc="lower right")
    for ax in axes:
        ax.tick_params(axis="y", which="both", left=False, right=False)
        ax.tick_params(axis="x", which="both", top=False)
    save(fig, "fig5_tradeoff")


def need() -> dict:
    """County food insecurity against SVI."""
    n = pd.read_csv(CTX / "county_need.csv").dropna(subset=["food_insecure_pct", "svi_overall"])
    rho = spearmanr(n["svi_overall"], n["food_insecure_pct"]).statistic
    fig, ax = plt.subplots(figsize=(3.3, 2.5))
    ax.scatter(n["svi_overall"], n["food_insecure_pct"], s=2, alpha=.35, color=BLUE, linewidths=0, rasterized=True)
    ax.set_xlabel("CDC/ATSDR SVI (county percentile)")
    ax.set_ylabel("Adults food insecure (%)")
    ax.text(.04, .92, f"Spearman $\\rho$ = {rho:.2f}, n = {len(n):,}", transform=ax.transAxes, fontsize=7.5)
    save(fig, "fig6_need")
    return {"rho": round(float(rho), 3), "n": len(n)}


if __name__ == "__main__":
    FIG.mkdir(parents=True, exist_ok=True)
    plt.style.use(["science", "no-latex"])
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Arial", "DejaVu Sans"], "font.size": 8})
    categories(); by_year(); forecast(); alert(); tradeoff()
    print(json.dumps(need()))
