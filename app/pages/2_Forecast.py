"""PoultryRescue — Next-month forecast (Streamlit page).

Run from the project root (appears in the sidebar):
    streamlit run app/dashboard.py

One-month-ahead forecast of human Salmonella isolates per state (CDC BEAM),
with the base model (M0: history, seasonality, trend) and the updated model
(M1: M0 + FSIS raw-poultry positivity, NOAA weather and storms). The excess
M1 - M0 shows which current conditions push risk above or below normal.

Results come from artifacts/forecast/ when `python run_all.py` has
been run; otherwise they are computed here (about a minute per target).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app import theme  # noqa: E402

from src import beam, forecast, geo, ingest_local  # noqa: E402

st.set_page_config(page_title="PoultryRescue — Forecast", page_icon="📈", layout="wide")
theme.inject()
st.html(
    """
    <style>
      .block-container { padding-top: 3rem; padding-bottom: 2rem; max-width: 1320px; }
      div[data-testid="stMetric"] { background:#ffffff; border:1px solid #e6e1ea;
          border-radius:10px; padding:.75rem 1rem; box-shadow:0 1px 3px rgba(0,0,0,.05); }
      div[data-testid="stMetricLabel"] p { font-weight:600; color:#555; }
      h2 { color:#12343B; }
      h3 { color:#12343B; }
    </style>
    """
)

ARTIFACT_DIR = PROJECT_ROOT / "artifacts" / "forecast"
TARGETS = {
    "Poultry-associated serotypes": ("poultry_serotypes", beam.POULTRY_SEROTYPES),
    "Enteritidis": ("enteritidis", ("Enteritidis",)),
    "All Salmonella": ("all_salmonella", None),
}
DIVERGING = [[0, "#2166ac"], [0.5, "#f7f7f7"], [1, "#b2182b"]]


# ---------------------------------------------------------------------------
# Data (artifacts if present, else computed and cached)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Running forecast and rolling validation (about a minute)…")
def load_results(key: str, serotypes: tuple[str, ...] | None) -> dict:
    files = {n: ARTIFACT_DIR / f"{n}_{key}.csv" for n in
             ("validation", "validation_national", "coefficients", "next_month")}
    if all(p.exists() for p in files.values()) and (ARTIFACT_DIR / "as_of.json").exists():
        val = pd.read_csv(files["validation"])
        nat = pd.read_csv(files["validation_national"])
        coef = pd.read_csv(files["coefficients"]).set_index("feature")
        nxt = pd.read_csv(files["next_month"])
        as_of = json.loads((ARTIFACT_DIR / "as_of.json").read_text())
        source = "saved results (artifacts/forecast)"
    else:
        feats1 = forecast.m1_features(serotypes)
        panel = forecast.build_panel(serotypes=serotypes, include_next=True)
        hist = panel.dropna(subset=["isolates"])
        v = forecast.rolling_validation(hist, feats1)
        val = v.predictions.assign(period=lambda d: d["period"].astype(str))
        nat = forecast.national_check(v.predictions)["national"].reset_index()
        nat["period"] = nat["period"].astype(str)
        coef = forecast.coefficient_table(hist, feats1)
        nxt = forecast.next_month_forecast(panel, feats1)
        nxt["period"] = nxt["period"].astype(str)
        as_of = panel.attrs["as_of"] | {"next_period": panel.attrs["next_period"]}
        source = "computed in this session"
    return {"val": val, "nat": nat, "coef": coef, "next": nxt, "as_of": as_of, "source": source}


@st.cache_data
def state_population() -> pd.Series:
    svi = ingest_local.load_svi_vulnerability(2022)
    return svi.groupby("state")["population"].sum()


def model_metrics(val: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, label in (("seasonal_naive", "Seasonal naive (same month last year)"),
                        ("persistence", "Persistence (last month)"),
                        ("m0", "M0 base: history + season + trend"),
                        ("m1", "M1 updated: M0 + FSIS + weather + storms")):
        err = val[name] - val["isolates"]
        rows.append({"Model": label, "MAE": err.abs().mean(), "RMSE": np.sqrt((err ** 2).mean())})
    m = pd.DataFrame(rows)
    m["Better than seasonal naive"] = (100 * (1 - m["MAE"] / m.loc[0, "MAE"])).round(1).astype(str) + "%"
    return m.round({"MAE": 2, "RMSE": 2})


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
st.title("Next-month Salmonella forecast")
target_name = st.selectbox("Forecast target (human isolates, CDC BEAM)", list(TARGETS),
                           help="Poultry-associated: Enteritidis, Infantis, Typhimurium, Kentucky, "
                                "Heidelberg, Schwarzengrund, Hadar.")
key, sero = TARGETS[target_name]
res = load_results(key, sero)
val, nat, coef, nxt, as_of = res["val"], res["nat"], res["coef"], res["next"], res["as_of"]
nxt_label = pd.Period(as_of["next_period"], "M").strftime("%B %Y")

st.caption(
    f"Forecast month: **{nxt_label}** · Human cases complete through {as_of['beam_complete_through']} · "
    f"FSIS through {as_of['fsis']} · Climate through {as_of['climate']} · Storms through {as_of['storms']} "
    f"· Results: {res['source']}"
)
if "storms_note" in as_of:
    st.caption(f"Note: {as_of['storms_note']}. Missing months use the latest available value.")

pop = state_population()
nxt["population"] = nxt["state"].map(pop)
nxt["m0_per100k"] = 1e5 * nxt["m0"] / nxt["population"]
extra = [f for f in forecast.m1_features(sero) if f not in forecast.M0_FEATURES]
contrib_cols = [f"contrib_{f}" for f in extra if f"contrib_{f}" in nxt.columns]
short = {"fsis_nat_oe": "Plant positivity (national)", "fsis_nat_sero": "Plant serotype positivity (national)",
         "fsis_state_oe": "Plant positivity (state)", "tmax_anom": "Heat anomaly",
         "precip_anom": "Rain anomaly", "log_storm_heat": "Heat events",
         "log_storm_flood": "Flood/tropical events", "log_storm_damage": "Storm damage"}
if contrib_cols:
    centered = nxt[contrib_cols] - nxt[contrib_cols].mean()
    top = centered.abs().idxmax(axis=1).str.replace("contrib_", "", regex=False)
    sign = np.sign(centered.to_numpy()[np.arange(len(nxt)), [contrib_cols.index("contrib_" + t) for t in top]])
    nxt["main_driver"] = [f"{short.get(t, t)} {'↑' if s > 0 else '↓'}" for t, s in zip(top, sign)]
else:
    nxt["main_driver"] = ""

m = model_metrics(val)
nat_total = nxt["m0"].sum()
# National range from how far national totals actually missed in validation
# (state errors are correlated, so summing state intervals would be too narrow).
ratio_lo, ratio_hi = np.quantile(nat["isolates"] / nat["m0"], [0.1, 0.9])
c1, c2, c3, c4 = st.columns(4)
def _compact(x: float) -> str:
    return f"{x / 1000:.1f}k" if x >= 1000 else f"{x:.0f}"


c1.metric("Expected cases", f"{nat_total:,.0f}",
          help=f"{nxt_label}: sum of M0 state forecasts (states with complete inputs).")
c2.metric("80% range", f"{_compact(nat_total * ratio_lo)}–{_compact(nat_total * ratio_hi)}",
          help="10th–90th percentile of actual/forecast for national totals in rolling validation.")
c3.metric("Gain vs same month last year", m.loc[2, "Better than seasonal naive"],
          help="One month ahead, a best case. This is a weak baseline. At 3 months against fair baselines the gain is 5-12%; see the main page.")
live = pd.read_csv(PROJECT_ROOT / "artifacts" / "context" / "live_outlook.csv")
c4.metric("States above alert level", int(live[live["period"] == live["period"].max()]["alert"].sum()),
          help="Three-month-ahead outlook for the latest month shown on the main page.")

# --- 1. Map --------------------------------------------------------------
st.header(f"1 · Forecast for {nxt_label}")
view = st.radio("Map shows", ["Expected cases per 100,000 (M0)",
                              "Excess: current conditions vs normal (M1 vs M0, %)"], horizontal=True)
if view.startswith("Expected"):
    z, scale, zmid, title = nxt["m0_per100k"], "Purples", None, "per 100k"
else:
    lim = max(5.0, float(nxt["excess_pct"].abs().max()))
    z, scale, zmid, title = nxt["excess_pct"].clip(-lim, lim), DIVERGING, 0.0, "Excess %"
hover = (nxt["state"].map(geo.to_name) + "<br>Expected " + nxt["m0"].round(0).astype(int).astype(str)
         + " cases (" + nxt["m0_per100k"].round(1).astype(str) + " per 100k)"
         + "<br>M1 " + nxt["m1"].round(0).astype(int).astype(str) + " (80%: "
         + nxt["m1_low80"].round(0).astype(int).astype(str) + "–"
         + nxt["m1_high80"].round(0).astype(int).astype(str) + ")"
         + "<br>Excess " + nxt["excess_pct"].round(1).astype(str) + "% · " + nxt["main_driver"])
fig = go.Figure(go.Choropleth(locations=nxt["state"], z=z, locationmode="USA-states",
                              colorscale=scale, zmid=zmid, text=hover, hoverinfo="text",
                              marker_line_color="white", colorbar_title=title))
fig.update_geos(showland=True, landcolor="#e5e5e5")
fig.update_layout(geo_scope="usa", height=450, margin=dict(l=0, r=0, t=10, b=0))
st.plotly_chart(fig, width="stretch")

# --- 2. Priority table -------------------------------------------------------
st.header("2 · State priority")
st.caption("Sorted by excess, which is context only. It has not improved forecast accuracy. "
           "This one-month view assumes last month's count is final, so treat it as a best case.")
tbl = nxt.assign(State=nxt["state"].map(geo.to_name))[
    ["State", "m0", "m1", "m1_low80", "m1_high80", "excess_pct", "excess_z", "main_driver"]]
st.dataframe(
    tbl.rename(columns={"m0": "Expected (M0)", "m1": "Updated (M1)", "m1_low80": "M1 80% low",
                        "m1_high80": "M1 80% high", "excess_pct": "Excess %", "excess_z": "Excess (noise units)",
                        "main_driver": "Main driver"})
    .round({"Expected (M0)": 0, "Updated (M1)": 0, "M1 80% low": 0, "M1 80% high": 0,
            "Excess %": 1, "Excess (noise units)": 2}),
    hide_index=True, width="stretch", height=380,
)

# --- 3. Validation ------------------------------------------------------------
st.header("3 · How well does it forecast?")
left, right = st.columns([3, 2])
with left:
    x = pd.PeriodIndex(nat["period"], freq="M").to_timestamp()
    fv = go.Figure()
    fv.add_trace(go.Scatter(x=x, y=nat["isolates"], name="Actual", line=dict(color="#111", width=2.5)))
    fv.add_trace(go.Scatter(x=x, y=nat["seasonal_naive"], name="Seasonal naive",
                            line=dict(color="#9aa3ad", dash="dash")))
    fv.add_trace(go.Scatter(x=x, y=nat["m0"], name="M0 base", line=dict(color="#2f6db5")))
    fv.add_trace(go.Scatter(x=x, y=nat["m1"], name="M1 updated", line=dict(color="#d9822b")))
    fv.update_layout(title="National total of 1-month-ahead state forecasts", height=360,
                     yaxis_title="Human isolates", margin=dict(l=0, r=0, t=40, b=0), legend_title="")
    st.plotly_chart(fv, width="stretch")
with right:
    st.dataframe(m, hide_index=True, width="stretch")
    st.caption("Rolling-origin validation: before each test month (2022 on) the models are refit on "
               "earlier months only. MAE = mean absolute error in cases per state-month.")

# --- 4. Look back --------------------------------------------------------------
st.header("4 · Look back: forecast vs. what happened")
st.caption("Each month was forecast using only data from earlier months (rolling validation), "
           "using today's final counts, so this is a retrospective test, not a real-time record.")
val["period"] = val["period"].astype(str)
months = sorted(val["period"].unique())
lb_month = st.select_slider("Month", options=months, value=months[-1],
                            format_func=lambda p: pd.Period(p, "M").strftime("%b %Y"))
lb = val[val["period"] == lb_month].copy()
lb["State"] = lb["state"].map(geo.to_name)
lb["error_m0_pct"] = 100 * (lb["m0"] - lb["isolates"]) / lb["isolates"].where(lb["isolates"] > 0)
tot = lb[["isolates", "m0", "m1", "seasonal_naive"]].sum()

k1, k2, k3, k4 = st.columns(4)
k1.metric("Actual cases", f"{tot['isolates']:,.0f}")
k2.metric("M0 forecast", f"{tot['m0']:,.0f}", f"{100 * (tot['m0'] / tot['isolates'] - 1):+.1f}% vs actual",
          delta_color="off")
k3.metric("M1 forecast", f"{tot['m1']:,.0f}", f"{100 * (tot['m1'] / tot['isolates'] - 1):+.1f}% vs actual",
          delta_color="off")
k4.metric("Seasonal naive", f"{tot['seasonal_naive']:,.0f}",
          f"{100 * (tot['seasonal_naive'] / tot['isolates'] - 1):+.1f}% vs actual", delta_color="off")

lb_l, lb_r = st.columns([3, 2])
with lb_l:
    lb["surprise_pct"] = 100 * (lb["isolates"] - lb["m0"]) / lb["m0"]
    lim = float(np.clip(lb["surprise_pct"].abs().quantile(0.95), 20, 200))
    hover_lb = (lb["State"] + "<br>Actual " + lb["isolates"].round(0).astype(int).astype(str)
                + " · M0 " + lb["m0"].round(0).astype(int).astype(str)
                + " · M1 " + lb["m1"].round(0).astype(int).astype(str)
                + "<br>Actual vs M0: " + lb["surprise_pct"].round(0).astype(int).astype(str) + "%")
    fm = go.Figure(go.Choropleth(locations=lb["state"], z=lb["surprise_pct"].clip(-lim, lim),
                                 locationmode="USA-states", colorscale=DIVERGING, zmid=0,
                                 text=hover_lb, hoverinfo="text", marker_line_color="white",
                                 colorbar_title="Actual<br>vs M0 %"))
    fm.update_geos(showland=True, landcolor="#e5e5e5")
    fm.update_layout(geo_scope="usa", height=400, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fm, width="stretch")
    st.caption("Red = more cases than forecast (a surprise surge); blue = fewer than forecast.")
with lb_r:
    st.dataframe(
        lb.sort_values("isolates", ascending=False)[["State", "isolates", "m0", "m1", "seasonal_naive"]]
        .rename(columns={"isolates": "Actual", "m0": "M0", "m1": "M1", "seasonal_naive": "Seasonal"})
        .round(0),
        hide_index=True, width="stretch", height=430)

state_opts = sorted(val["state"].unique())
pick = st.selectbox("State history", state_opts, index=state_opts.index("MD") if "MD" in state_opts else 0,
                    format_func=geo.to_name)
sh = val[val["state"] == pick].copy()
xs = pd.PeriodIndex(sh["period"], freq="M").to_timestamp()
fs = go.Figure()
fs.add_trace(go.Scatter(x=xs, y=sh["isolates"], name="Actual", line=dict(color="#111", width=2.5)))
fs.add_trace(go.Scatter(x=xs, y=sh["seasonal_naive"], name="Seasonal naive", line=dict(color="#9aa3ad", dash="dash")))
fs.add_trace(go.Scatter(x=xs, y=sh["m0"], name="M0 base", line=dict(color="#2f6db5")))
fs.add_trace(go.Scatter(x=xs, y=sh["m1"], name="M1 updated", line=dict(color="#d9822b")))
fs.add_vline(x=pd.Period(lb_month, "M").to_timestamp(), line_dash="dot", line_color="#12343B")
fs.update_layout(title=f"{geo.to_name(pick)}: actual vs 1-month-ahead forecasts", height=340,
                 yaxis_title="Human isolates", margin=dict(l=0, r=0, t=40, b=0), legend_title="")
st.plotly_chart(fs, width="stretch")

# --- 5. What moves risk ------------------------------------------------------
st.header("5 · What moves risk")
c = coef.drop(index=[f for f in forecast.M0_FEATURES if f in coef.index])
fc = go.Figure(go.Scatter(
    x=c["rate_ratio"], y=c["label"], mode="markers", marker=dict(size=9, color="#12343B"),
    error_x=dict(type="data", symmetric=False, array=c["ci_high"] - c["rate_ratio"],
                 arrayminus=c["rate_ratio"] - c["ci_low"], color="#9aa3ad"),
    hovertemplate="%{y}<br>rate ratio %{x:.3f}<extra></extra>"))
fc.add_vline(x=1, line_dash="dot", line_color="#888")
fc.update_layout(height=60 * len(c) + 80, xaxis_title="Rate ratio per unit change (95% CI)",
                 margin=dict(l=0, r=0, t=10, b=0), yaxis=dict(autorange="reversed"))
st.plotly_chart(fc, width="stretch")
sig = c[(c["ci_low"] > 1) | (c["ci_high"] < 1)]
sig_text = ("; ".join(f"{row.label} (rate ratio {row.rate_ratio:.3f}, 95% CI "
                      f"{row.ci_low:.3f}–{row.ci_high:.3f})" for row in sig.itertuples())
            or "none of the current signals")
m1_gain = 100 * (1 - m.loc[3, "MAE"] / m.loc[2, "MAE"])
st.info(
    f"Reading this: a rate ratio above 1 means more cases the following month. For {target_name}, "
    f"the signals with a confidence interval excluding 1 are: {sig_text}. In rolling validation, M1 changes "
    f"forecast error by {m1_gain:+.1f}% relative to M0, so current conditions do not add measurable "
    "accuracy beyond history, season and trend. The excess is context for *why* risk may be elevated, "
    "not a stand-alone alarm. Decision support only, not a regulatory determination."
)
