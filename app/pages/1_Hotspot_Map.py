"""Early Signal — Hotspot Map (Streamlit page).

Run from the project root (the page appears in the sidebar next to the main
dashboard):
    streamlit run app/dashboard.py

Where is raw-poultry Salmonella above what each state's sample mix predicts,
and how does that overlap with food-security need?

  * Food + animal stream: REAL FSIS Raw Poultry Sampling (src.fsis_raw).
  * Food-security stream: CDC/ATSDR SVI 2022 county profile (src.ingest_local).
  * Hotspots are ranked by the product-mix-adjusted observed/expected ratio
    (O/E) with a 95% CI, so a state is not flagged just because it samples more
    ground product.
  * Region comparison panel design inspired by AgriTiles
    (Cisdeli, Santiago & Ciampitti; MIT License).
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app import theme  # noqa: E402

from src import fsis_raw, geo, ingest_local  # noqa: E402

st.set_page_config(page_title="Early Signal — Hotspot Map", page_icon="🗺️", layout="wide")
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

COLOR_A, COLOR_B = "#3b82f6", "#f59e0b"
OE_SCALE = [[0, "#2166ac"], [0.5, "#f7f7f7"], [1, "#b2182b"]]   # blue < 1 < red


# ---------------------------------------------------------------------------
# Data (cached)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Loading FSIS raw poultry samples…")
def load_samples() -> pd.DataFrame:
    return fsis_raw.load_raw_poultry()


@st.cache_data(show_spinner="Loading county vulnerability…")
def load_svi() -> pd.DataFrame:
    return ingest_local.load_svi_vulnerability(2022)


@st.cache_data(show_spinner="Loading county boundaries…")
def load_geojson() -> dict:
    return fsis_raw.load_county_geojson()


def svi_profile(svi: pd.DataFrame, states: list[str]) -> dict:
    """Population-weighted vulnerability summary for a set of states."""
    d = svi[svi["state"].isin(states)]
    if d.empty:
        return {}
    w = d["population"]
    return {
        "counties": len(d),
        "population": int(w.sum()),
        "svi_weighted": float((d["svi_overall"] * w).sum() / w.sum()),
        "high_svi_counties": int((d["svi_overall"] >= 0.75).sum()),
        "pct_pov150": float((d["pct_pov150"] * w).sum() / w.sum()),
    }


try:
    samples = load_samples()
except FileNotFoundError as err:
    st.error(str(err))
    st.stop()
svi = load_svi()

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Filters")
    routine = st.toggle("Routine sampling only", value=True,
                        help="Excludes follow-up sampling of plants that already failed, plus "
                             "exploratory and outbreak-response projects, which overstate positivity.")
    groups = sorted(g for g in samples["product_group"].unique() if g != "Other")
    sel_groups = st.multiselect("Product type", groups, default=groups)
    months = sorted(samples["month"].unique())
    m_start, m_end = st.select_slider(
        "Months", options=months, value=(months[max(0, len(months) - 12)], months[-1]),
        format_func=lambda p: p.strftime("%b %Y"),
        help="Defaults to the latest 12 months; drag to compare earlier years.")
    min_samples = st.slider("Minimum samples per state", 50, 500, 150, step=25,
                            help="States with fewer samples are hidden to avoid noisy rates.")

df = samples[samples["product_group"].isin(sel_groups)
             & samples["month"].between(m_start, m_end)
             & (samples["routine"] if routine else True)]
if df.empty:
    st.warning("No samples match the filters.")
    st.stop()

state_tbl = fsis_raw.state_summary(df, min_samples=min_samples)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("Raw poultry Salmonella hotspots")
st.caption(
    f"FSIS Raw Poultry Sampling (USDA, real data) · {m_start.strftime('%b %Y')}–"
    f"{m_end.strftime('%b %Y')} · CDC/ATSDR SVI 2022"
)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Samples", f"{len(df):,}")
c2.metric("Salmonella positive", f"{100 * df['positive'].mean():.1f}%")
c3.metric("Plants sampled", f"{df['establishment_id'].nunique():,}")
c4.metric("Significant hotspot states", int(state_tbl["hotspot"].sum()),
          help="95% CI of the product-mix-adjusted O/E lies entirely above 1, in a state with at least 10 plants.")

# ---------------------------------------------------------------------------
# 1. National map
# ---------------------------------------------------------------------------
st.header("1 · Where is Salmonella above expected?")
metric = st.radio(
    "Map shows",
    ["Adjusted O/E (recommended)", "Raw % positive", "Samples"],
    horizontal=True,
    help="O/E compares each state's positives with what its mix of product types "
         "predicts at national rates. 1.0 = as expected; 1.5 = 50% more positives.",
)
tbl = state_tbl.reset_index()
hover = (tbl["state_name"] + "<br>O/E " + tbl["o_e"].astype(str)
         + " (95% CI " + tbl["o_e_low"].astype(str) + "–" + tbl["o_e_high"].astype(str) + ")"
         + "<br>" + tbl["pct_positive"].astype(str) + "% positive · "
         + tbl["samples"].astype(str) + " samples · " + tbl["plants"].astype(str) + " plants"
         + "<br>Top serotype: " + tbl["top_serotype"].fillna("n/a"))

if metric.startswith("Adjusted"):
    z, scale, zmid, title = tbl["o_e"], OE_SCALE, 1.0, "O/E"
elif metric.startswith("Raw"):
    z, scale, zmid, title = tbl["pct_positive"], "Reds", None, "% positive"
else:
    z, scale, zmid, title = tbl["samples"], "Purples", None, "Samples"

fig = go.Figure(go.Choropleth(
    locations=tbl["state"], z=z, locationmode="USA-states", colorscale=scale, zmid=zmid,
    text=hover, hoverinfo="text", marker_line_color="white", marker_line_width=0.8,
    colorbar_title=title,
))
hot = tbl[tbl["hotspot"]]
if not hot.empty:  # outline significant hotspots
    fig.add_trace(go.Choropleth(
        locations=hot["state"], z=[1] * len(hot), locationmode="USA-states",
        colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]], showscale=False,
        marker_line_color="#111", marker_line_width=2.5, hoverinfo="skip",
    ))
fig.update_geos(showland=True, landcolor="#e5e5e5", showlakes=False)
fig.update_layout(geo_scope="usa", height=470, margin=dict(l=0, r=0, t=10, b=0))
st.plotly_chart(fig, width="stretch")
st.caption("Bold outline = significant hotspot. Grey = fewer samples than the minimum.")

with st.expander("State table"):
    st.dataframe(
        tbl[["state_name", "samples", "plants", "pct_positive", "o_e", "o_e_low",
             "o_e_high", "hotspot", "top_serotype"]]
        .rename(columns={"state_name": "State", "pct_positive": "% positive",
                         "o_e": "O/E", "o_e_low": "CI low", "o_e_high": "CI high"}),
        hide_index=True, width="stretch",
    )

# ---------------------------------------------------------------------------
# 2. Hotspot zoom
# ---------------------------------------------------------------------------
st.header("2 · Hotspot zoom: Salmonella risk and community need")
region_name = st.selectbox("Region", list(fsis_raw.REGIONS))
region = fsis_raw.REGIONS[region_name]
reg_tbl = tbl[tbl["state"].isin(region)]
reg_svi = svi[svi["state"].isin(region)]

left, right = st.columns([3, 2])
with left:
    need = st.radio("Shade counties by", ["SVI (overall vulnerability)",
                                          "% below 150% poverty (food-insecurity proxy)"],
                    horizontal=True)
    col = "svi_overall" if need.startswith("SVI") else "pct_pov150"
    if not reg_tbl.empty:  # state-level raw-poultry O/E above the county map
        chips = [f"**{r.state}** {r.o_e:.2f}" + (" (hotspot)" if r.hotspot else "")
                 for r in reg_tbl.sort_values("o_e", ascending=False).itertuples()]
        st.markdown("Raw-poultry O/E by state: " + " · ".join(chips))
    cmap = px.choropleth(
        reg_svi, geojson=load_geojson(), locations="FIPS", color=col,
        color_continuous_scale="Purples", hover_name="county",
        hover_data={"FIPS": False, "state": True, "population": ":,",
                    "svi_overall": ":.2f", "pct_pov150": ":.1f"},
        labels={"svi_overall": "SVI", "pct_pov150": "% <150% poverty"},
    )
    cmap.update_geos(fitbounds="locations", visible=False)
    cmap.update_layout(height=480, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(cmap, width="stretch")
    st.caption("Counties shaded by need.")

with right:
    reg_all = fsis_raw.add_expected(df)
    reg_all = reg_all[reg_all["state"].isin(region)]
    if len(reg_all):
        reg_oe = reg_all["positive"].sum() / reg_all["expected"].sum()
        prof = svi_profile(svi, region)
        a, b = st.columns(2)
        a.metric("Region O/E", f"{reg_oe:.2f}")
        b.metric("% positive", f"{100 * reg_all['positive'].mean():.1f}%")
        a.metric("High-SVI counties", f"{prof.get('high_svi_counties', 0)} / {prof.get('counties', 0)}")
        b.metric("Pop. <150% poverty", f"{prof.get('pct_pov150', 0):.1f}%")
        mix = fsis_raw.serotype_mix(df, region)
        if not mix.empty:
            fig_mix = px.bar(mix[::-1], orientation="h", labels={"value": "% of positives", "index": ""})
            fig_mix.update_layout(height=230, showlegend=False, margin=dict(l=0, r=0, t=30, b=0),
                                  title="Serotypes in positive samples")
            fig_mix.update_traces(marker_color="#12343B")
            st.plotly_chart(fig_mix, width="stretch")
        st.dataframe(fsis_raw.product_mix(df, region)
                     .rename(columns={"pct_positive": "% positive", "pct_of_samples": "% of samples"}),
                     width="stretch")
    else:
        st.info("No FSIS samples in this region with the current filters.")

# ---------------------------------------------------------------------------
# 3. Compare A vs B
# ---------------------------------------------------------------------------
st.header("3 · Compare two states")
opts = tbl["state"].tolist()
names = {s: geo.to_name(s) for s in opts}
default_a = opts.index("MD") if "MD" in opts else 0
default_b = opts.index("GA") if "GA" in opts else min(1, len(opts) - 1)
ca, cb = st.columns(2)
sa = ca.selectbox("State A", opts, index=default_a, format_func=names.get)
sb = cb.selectbox("State B", opts, index=default_b, format_func=names.get)

rows = []
for s in (sa, sb):
    r = tbl.set_index("state").loc[s]
    p = svi_profile(svi, [s])
    rows.append({
        "Samples": f"{int(r['samples']):,}", "Plants": str(int(r["plants"])),
        "% positive": f"{r['pct_positive']:.1f}%",
        "Adjusted O/E (95% CI)": f"{r['o_e']:.2f} ({r['o_e_low']:.2f}–{r['o_e_high']:.2f})",
        "Significant hotspot": "Yes" if r["hotspot"] else "No",
        "Top serotype": r["top_serotype"] if pd.notna(r["top_serotype"]) else "n/a",
        "Population-weighted SVI": f"{p.get('svi_weighted', float('nan')):.2f}",
        "High-SVI counties": f"{p.get('high_svi_counties', 0)} of {p.get('counties', 0)}",
        "Pop. below 150% poverty": f"{p.get('pct_pov150', float('nan')):.1f}%",
    })
cmp = pd.DataFrame(rows, index=[names[sa], names[sb]]).T
st.dataframe(cmp, width="stretch")

g1, g2 = st.columns(2)
with g1:
    mix_a, mix_b = fsis_raw.serotype_mix(df, [sa]), fsis_raw.serotype_mix(df, [sb])
    mix = pd.concat({names[sa]: mix_a, names[sb]: mix_b}, axis=1).fillna(0)
    order = [s for s in mix.sum(axis=1).sort_values(ascending=False).index if s != "Other"]
    mix = mix.loc[order + (["Other"] if "Other" in mix.index else [])].reset_index(names="serotype")
    long = mix.melt(id_vars="serotype", var_name="state", value_name="share")
    fig_c = px.bar(long, x="share", y="serotype", color="state", barmode="group", orientation="h",
                   color_discrete_sequence=[COLOR_A, COLOR_B],
                   labels={"share": "% of positives", "serotype": ""}, title="Serotype mix")
    fig_c.update_layout(height=340, margin=dict(l=0, r=0, t=40, b=0), legend_title="",
                        yaxis=dict(categoryorder="array", categoryarray=mix["serotype"][::-1].tolist()))
    st.plotly_chart(fig_c, width="stretch")
with g2:
    ma, mb = fsis_raw.monthly_positivity(df, [sa]), fsis_raw.monthly_positivity(df, [sb])
    fig_t = go.Figure()
    fig_t.add_trace(go.Scatter(x=ma.index, y=ma["o_e"], name=names[sa], line_color=COLOR_A, mode="lines+markers"))
    fig_t.add_trace(go.Scatter(x=mb.index, y=mb["o_e"], name=names[sb], line_color=COLOR_B, mode="lines+markers"))
    fig_t.add_hline(y=1, line_dash="dot", line_color="#888")
    fig_t.update_layout(title="Monthly adjusted O/E", height=340, yaxis_title="O/E",
                        margin=dict(l=0, r=0, t=40, b=0), legend_title="")
    st.plotly_chart(fig_t, width="stretch")
    st.caption(f"Samples per month: {names[sa]} ≈ {int(ma['samples'].mean())}, "
               f"{names[sb]} ≈ {int(mb['samples'].mean())}. With under ~100 samples a month, "
               "single-month swings are mostly noise; read the overall level, not the spikes.")

st.divider()
st.caption(
    "Decision support only, not a regulatory determination. FSIS says these data should not be used to identify outbreaks or link samples to them. Positivity reflects FSIS "
    "verification sampling, which is risk-weighted and not a random survey of all product. "
    f"Data files loaded: {', '.join(p.name for p in fsis_raw.raw_poultry_files())}. "
    "Comparison panel design inspired by AgriTiles (Cisdeli, Santiago & Ciampitti; MIT License)."
)
