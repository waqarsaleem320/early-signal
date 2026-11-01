"""Early Signal: lot decision page for a small or very small ground poultry plant.

Run from the project root:  streamlit run app/dashboard.py
Needs artifacts from:       python run_all.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402

from app import theme  # noqa: E402
from src import geo  # noqa: E402
from src.decision import actions as A  # noqa: E402

ART = ROOT / "artifacts"
FSIS_NOTE = ("FSIS states its sampling data are informational and should not be used to identify "
             "outbreaks, link samples to outbreaks, or show that samples are causally related. "
             "This tool is decision support, not a regulatory determination. A qualified person "
             "must review every high-consequence decision.")

st.set_page_config(page_title="Early Signal", page_icon="🐔", layout="wide")
theme.inject()


@st.cache_data
def tables() -> dict:
    ctx = ART / "context"
    return {
        "live": pd.read_csv(ctx / "live_outlook.csv"),
        "storms": pd.read_csv(ctx / "storm_months.csv"),
        "rates": pd.read_csv(ctx / "product_rates.csv"),
        "cats": pd.read_csv(ctx / "category_summary.csv"),
        "forward": pd.read_csv(ctx / "category_forward_rates.csv"),
        "published": pd.read_csv(ctx / "category_published_rates.csv"),
        "agree": pd.read_csv(ctx / "category_status_agreement.csv"),
        "persist": pd.read_csv(ctx / "plant_persistence.csv"),
        "scen": pd.read_csv(ART / "scenarios" / "scenario_results.csv"),
        "acc": pd.read_csv(ART / "outlook" / "accuracy_h3.csv"),
        "alerts": pd.read_csv(ART / "outlook" / "alert_backtest.csv"),
        "sero": pd.read_csv(ctx / "nors_serotypes.csv"),
        "years": pd.read_csv(ART / "outlook" / "alert_by_year.csv"),
    }


T = tables()
inp = A.load_inputs()

theme.brand()

with st.sidebar:
    st.header("Your lot")
    states = sorted(T["live"]["state"].unique())
    state = st.selectbox("Plant state", states, index=states.index("MO"), format_func=geo.to_name)
    period = T["live"]["period"].max()
    st.caption(f"Outlook month: {period}")
    product = st.selectbox("Product", list(A.PRODUCTS))
    lot_lb = st.number_input("Lot size (lb)", 100, 500_000, 10_000, step=500)
    cat = st.selectbox("FSIS Salmonella category for this product line",
                       ["Not listed", 1, 2, 3], index=1)
    cooked = st.checkbox("Plant has a validated cooked line", value=False)
    spec = st.checkbox("A buyer's Salmonella specification applies")
    result = st.selectbox("Lot screen result", ["none", "negative", "detected"])
    cfu = None
    if product == "Raw breaded stuffed chicken":
        cfu = st.text_input("Quantified result (CFU/g), if any", "") or None
    hours = st.number_input("Hours product was above 40°F", 0.0, 72.0, 0.0, step=0.5)
    limit = st.number_input("Time limit above 40°F from your HACCP plan (hours)", 0.5, 24.0,
                            A.MAX_HOURS_ABOVE_40F, step=0.5,
                            help="Default is the FSIS consumer guidance of 2 hours.")
    with st.expander("Check your own FSIS results"):
        n_samples = st.number_input("Routine FSIS samples, your plant's last 52 weeks", min_value=0,
                                    value=0, step=1, key="plant_samples")
        n_pos = st.number_input("Positives among those samples", min_value=0, value=0, step=1,
                                key="plant_positives")
    with st.expander("Change the assumptions"):
        donate = st.slider("Share donated after cooking", 0, 100, int(A.DONATED_SHARE * 100), 5) / 100
        detect = st.slider("Share of positives the test finds", 50, 100,
                           int(A.TEST_DETECTION_SHARE * 100), 5) / 100

row = T["live"][(T["live"]["state"] == state) & (T["live"]["period"] == period)].iloc[0]
month = int(period[-2:])
s = A.Situation(state=state, month=month, product=product, lot_lb=float(lot_lb),
                fsis_category=None if cat == "Not listed" else int(cat),
                has_cooked_line=cooked, customer_limit=spec, lot_result=result, cfu_per_g=cfu,
                hours_above_40f=float(hours), max_hours_above_40f=float(limit),
                plant_samples=int(n_samples), plant_positives=int(n_pos))
level, pct, why = A.risk_level(s, inp)
pick, reason = A.recommend(s, inp)
table = A.compare_actions(s, inp, test_detection=detect, donated_share=donate)

check = A.plant_self_check(s)
std = inp["standard"][A.PRODUCTS[product][0]]
theme.disposition_tag(level, pick, reason, pct, std, check.observed_pct if check else None)
why_tab, compare_tab, donate_tab, cases_tab, trust_tab = st.tabs(
    ["Why this call", "Compare options", "Donated meals", "Worked examples", "How far to trust this"])

with why_tab:
    for w in why:
        st.markdown(f"- {w}")
    st.caption("A Category 1 line can still read Elevated: the level uses what such lines measured the "
               "next year, which can sit above half the standard. An unlisted line uses the national rate, "
               "or the category rebuilt from your own samples when you enter at least 10.")
    if check is not None:
        st.subheader("Your plant's self-check")
        if check.status is None:
            st.warning(check.message)
        else:
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("Observed positive", f"{check.observed_pct:.1f}%")
            d2.metric("Samples / positives", f"{check.samples} / {check.positives}")
            d3.metric("Rebuilt category", f"Category {check.status}")
            d4.metric("FSIS standard", f"{check.standard_pct:g}%")
            st.info(check.message)
            if check.published_note:
                st.warning(check.published_note)
        st.caption(A.SELF_CHECK_NOTE)
    st.subheader(f"{geo.to_name(state)} this month")
    storm = T["storms"][(T["storms"]["state"] == state) & (T["storms"]["month"] == month)]
    years = f"{int(storm['years_with_event'].iloc[0])} of 12 years" if len(storm) else "no years listed"
    st.markdown(f"About **{row['expected_cases']:.0f}** poultry-associated human cases expected in {period} "
                f"(80% range {row['low_80']:.0f} to {row['high_80']:.0f}; three-year average "
                f"{row['baseline_3y']:.0f}), {'above' if row['alert'] else 'within'} the alert level. "
                f"Heat, flood or tropical events in this month: {years}.")
    st.caption("State figures are context and do not change the risk level. Salmonella-positive raw "
               "poultry is generally not adulterated. The exception is the narrow 2024 determination "
               "for raw breaded stuffed chicken, where FSIS verification sampling is delayed.")

with compare_tab:
    theme.action_table(table, pick)
    st.caption("Exposure index: national chicken parts sold raw = 1.0, scaled by what lines in your "
               "FSIS category measured the following year. It is relative, not a count of illnesses.")
    note = A.PRODUCTS[product][3]
    if note:
        st.caption(note)
    with st.expander("Notes on each action"):
        st.dataframe(table[["action", "note"]].rename(columns={"action": "Action", "note": "Notes"}),
                     hide_index=True, width="stretch")

with donate_tab:
    donated = float(table["servings_to_need"].max())
    st.caption("Highest-need counties in the plant's state, from CDC food insecurity (modeled, not in "
               "every state), CDC Social Vulnerability Index and USDA low-income, low-access share. "
               "Food organizations come from the IRS exempt list, so many church pantries are missing. "
               "Confirm capacity with the organization first. Donated cooked product needs Listeria "
               "controls (9 CFR 430) and cold chain to the food bank.")
    d = A.donation_targets(state, inp["need"], donated).rename(columns={
        "county": "County", "need_score": "Need score", "food_insecure_pct": "Adults food insecure %",
        "food_orgs": "Food orgs listed", "largest_food_org": "Largest listed", "svi_overall": "SVI",
        "lila_pop_share": "Low-income low-access share", "people_low_income": "People below 150% of poverty",
        "servings": "Servings"})
    st.dataframe(d, hide_index=True, width="stretch")

with cases_tab:
    sc = T["scen"]
    name = st.selectbox("Example", list(sc["scenario"].unique()))
    one = sc[sc["scenario"] == name]
    picked = one.loc[one["recommended"], "action"].iloc[0]
    st.markdown(f"Risk level: **{one['risk_level'].iloc[0]}**. {one['why'].iloc[0]}")
    theme.action_table(one, picked)

with trust_tab:
    st.subheader("A plant's category predicts its next year")
    f = T["published"][T["published"]["product_group"] != "Turkey carcass"]
    groups = list(f["product_group"].unique())
    fig = make_subplots(rows=1, cols=len(groups), shared_yaxes=True, subplot_titles=groups)
    for i, g in enumerate(groups, 1):
        r = f[f["product_group"] == g]
        fig.add_bar(x=[f"Cat {c}" for c in r["category"]], y=r["pct_positive_next_year"], row=1, col=i,
                    marker_color=[list(theme.LEVEL_COLOR.values())[c - 1] for c in r["category"]],
                    error_y=dict(type="data", symmetric=False, color=theme.INK, thickness=1.2, width=3,
                                 array=r["ci_high"] - r["pct_positive_next_year"],
                                 arrayminus=r["pct_positive_next_year"] - r["ci_low"]),
                    customdata=r[["plants", "samples"]],
                    hovertemplate="%{y:.1f}% positive next year<br>%{customdata[0]} plants, "
                                  "%{customdata[1]:,} samples<extra></extra>",
                    showlegend=False)
        fig.add_hline(y=r["fsis_standard_pct"].iloc[0], row=1, col=i, line_color=theme.INK, line_dash="dot",
                      line_width=1.5, annotation_text=f"Standard {r['fsis_standard_pct'].iloc[0]:g}%",
                      annotation_position="top left", annotation_font_size=11)
    fig.update_layout(height=340, margin=dict(l=0, r=0, t=34, b=0), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="#FFFFFF", font=dict(family="IBM Plex Sans", color=theme.INK), bargap=.28)
    fig.update_yaxes(gridcolor="#E3EAEC", ticksuffix="%", zeroline=False)
    st.plotly_chart(fig, width="stretch")
    st.caption("Share positive after a line received each published FSIS category, using four archived "
               "postings and the FSIS routine samples that followed them. Bars show 95% intervals that "
               "resample plants. Few Category 1 and 2 ground lines qualify, so those bars are wide.")
    with st.expander("Rates tables, and the same test on rebuilt categories"):
        st.dataframe(T["published"], hide_index=True, width="stretch")
        st.caption("Rebuilt from one 52-week window of routine samples, for three year-pairs. The "
                   "self-check uses these rates when a line has no published category.")
        st.dataframe(T["forward"], hide_index=True, width="stretch")
        st.dataframe(T["agree"], hide_index=True, width="stretch")
    with st.expander("State case forecast and alert backtest"):
        st.dataframe(T["acc"], hide_index=True, width="stretch")
        a = T["alerts"][T["alerts"]["rule"] == "forecast_ratio"]
        st.dataframe(a.drop(columns="rule"), hide_index=True, width="stretch")
        y = T["years"][T["years"]["target"] == "poultry_serotypes"]
        st.dataframe(y[["year", "months", "alerts", "precision", "surge_rate", "recall"]],
                     hide_index=True, width="stretch")
        st.caption("The threshold was set on 2022-2023 and applied unchanged from 2024. The alert held "
                   "in 2024-2025 and failed in 2026, and we do not know why, so it does not drive the "
                   "risk level. This is a retrospective test using the latest data. A surge means "
                   "well above the last three years, which is not the same as an outbreak.")
    with st.expander("Other measured context"):
        st.dataframe(T["rates"], hide_index=True, width="stretch")
        st.dataframe(T["cats"], hide_index=True, width="stretch")
        st.dataframe(T["persist"], hide_index=True, width="stretch")
        st.dataframe(T["sero"], hide_index=True, width="stretch")
    st.warning("**What this tool does not do:** it does not predict outbreaks, count illnesses avoided, "
               "or judge any company. FSIS and weather data did not improve the state case forecast.")
    st.caption(FSIS_NOTE)
