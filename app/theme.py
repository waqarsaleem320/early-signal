"""Look of the app: a QA disposition tag, a gauge against the FSIS standard, and an
action table. Display only. Every number comes from src/decision."""
from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

INK = "#12343B"
LEVEL_COLOR = {"Low": "#1F7A5C", "Elevated": "#9A6200", "High": "#A8261B"}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@85,500;85,700;85,800&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
:root { --ink:#12343B; --steel:#5B7077; --line:#CFDADD; --plate:#FFFFFF; --cold:#EDF2F3;
        --chill:#2B7A9E; --good:#1F7A5C; --warn:#9A6200; --bad:#A8261B; }
.stApp { background:var(--cold); color:var(--ink); }
.stApp, .stApp p, .stApp label, .stApp input, .stApp li { font-family:'IBM Plex Sans',sans-serif; }
.stApp h1, .stApp h2, .stApp h3 { font-family:'Archivo',sans-serif; font-stretch:85%;
    color:var(--ink); font-weight:700; letter-spacing:-.005em; }
[data-testid="stHeader"] { background:transparent; }
.stTabs [data-baseweb="tab-highlight"] { background-color:var(--chill) !important; }
.block-container { max-width:1120px; padding-top:3.4rem; padding-bottom:3rem; }
[data-testid="stSidebar"] { background:var(--ink); }
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] label, [data-testid="stSidebar"] p,
[data-testid="stSidebar"] summary, [data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color:#E4EDEF; }
[data-testid="stSidebar"] [data-testid="stExpander"] { border-color:#2F5560; background:transparent; }
[data-testid="stToolbar"] { visibility:hidden; }
[data-testid="stMetric"] { background:var(--plate); border-left:3px solid var(--line); padding:.6rem .9rem; }
.stTabs [data-baseweb="tab"] { font-family:'Archivo',sans-serif; font-stretch:85%; font-weight:700; font-size:1.02rem; }
.stTabs [aria-selected="true"] { color:var(--chill); }
.brand { display:flex; align-items:baseline; gap:.8rem; flex-wrap:wrap; margin-bottom:1.1rem; }
.brand b { font:800 1.9rem/1 'Archivo',sans-serif; font-stretch:85%; color:var(--ink); }
.brand span { color:var(--steel); font-size:.95rem; }
.tag { position:relative; background:var(--plate); border-left:14px solid var(--level);
       padding:1.5rem 1.7rem 1.4rem 3.5rem; clip-path:polygon(0 0,calc(100% - 26px) 0,100% 26px,100% 100%,0 100%);
       animation:tag-in .32s ease-out; }
.tag::before { content:""; position:absolute; left:1.1rem; top:1.75rem; width:1.05rem; height:1.05rem;
       border-radius:50%; background:var(--cold); box-shadow:inset 0 0 0 2px var(--level); }
.tag .lvl { color:var(--level); font-weight:600; font-size:1rem; }
.tag .act { font:800 clamp(1.9rem,4.4vw,3rem)/1.06 'Archivo',sans-serif; font-stretch:85%;
            color:var(--ink); margin:.1rem 0 .55rem; max-width:22ch; }
.tag .why { color:#2E4B52; max-width:70ch; line-height:1.5; margin:0; }
@keyframes tag-in { from { transform:translateX(-10px); opacity:.2; } }
.gauge { margin:1.5rem 0 .3rem; }
.track { position:relative; height:16px; display:flex; }
.track i { display:block; height:100%; }
.pin { position:absolute; top:-7px; width:4px; height:30px; background:var(--ink); transform:translateX(-2px); }
.pin.own { background:var(--chill); }
.pinlabel { position:absolute; top:-30px; transform:translateX(-50%); white-space:nowrap; font-weight:600; font-size:.88rem; color:var(--ink); }
.pinlabel.own { top:auto; bottom:-30px; color:var(--chill); }
.scale { position:relative; height:1.5rem; margin-top:.3rem; color:var(--steel); font-size:.8rem; }
.scale span { position:absolute; transform:translateX(-50%); white-space:nowrap; }
.gaugebox { padding-top:1.5rem; padding-bottom:.9rem; }
.acts { width:100%; border-collapse:collapse; background:var(--plate); }
.acts th { text-align:left; font-weight:600; color:var(--steel); font-size:.84rem; padding:.6rem .8rem; border-bottom:2px solid var(--line); }
.acts td { padding:.65rem .8rem; border-bottom:1px solid var(--line); vertical-align:middle; }
.acts td.n, .acts th.n { text-align:right; font-variant-numeric:tabular-nums; }
.acts tr.pick { box-shadow:inset 4px 0 0 var(--chill); }
.acts tr.pick td:first-child { font-weight:600; }
.acts tr.no td { color:#8A9BA0; }
.bar { display:flex; align-items:center; gap:.5rem; min-width:130px; }
.bar i { display:block; height:9px; background:var(--chill); border-radius:0 4px 4px 0; }
.acts tr.no .bar i { background:var(--line); }
.scroll { overflow-x:auto; }
@media (prefers-reduced-motion:reduce) { .tag { animation:none; } }
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def brand() -> None:
    st.markdown("<div class='brand'><b>Early Signal</b><span>Salmonella lot decisions for small "
                "ground poultry plants</span></div>", unsafe_allow_html=True)


def _gauge(pct: float, std: float, own: float | None) -> str:
    top = max(std * 2, pct * 1.15, (own or 0) * 1.15)
    x = lambda v: round(100 * v / top, 2)  # noqa: E731
    zones = "".join(f"<i style='width:{w}%;background:{c}'></i>" for w, c in (
        (x(std / 2), "#BFE0D3"), (x(std / 2), "#F0DDAE"), (100 - x(std), "#EDC1BB")))
    pins = (f"<div class='pinlabel' style='left:{min(max(x(pct), 12), 88)}%'>Expected {pct:.1f}%</div>"
            f"<div class='pin' style='left:{x(pct)}%'></div>")
    if own is not None:
        pins += (f"<div class='pinlabel own' style='left:{min(max(x(own), 12), 88)}%'>Your samples {own:.1f}%</div>"
                 f"<div class='pin own' style='left:{x(own)}%'></div>")
    scale = (f"<span style='left:{x(std / 2)}%'>Half the standard {std / 2:g}%</span>"
             f"<span style='left:{x(std)}%'>FSIS standard {std:g}%</span>")
    return (f"<div class='gauge' role='img' aria-label='Expected positivity {pct:.1f} percent, "
            f"FSIS standard {std:g} percent'><div class='track'>{zones}{pins}</div>"
            f"<div class='scale'{' style=margin-top:1.9rem' if own is not None else ''}>{scale}</div></div>")


def disposition_tag(level: str, action: str, reason: str, pct: float, std: float,
                    own: float | None = None) -> None:
    """The recommendation, as the tag a QA lead would hang on the lot."""
    st.markdown(
        f"<section class='tag' style='--level:{LEVEL_COLOR[level]}'>"
        f"<div class='lvl'>{level} risk</div><div class='act'>{escape(action)}</div>"
        f"<p class='why'>{escape(reason)}</p>"
        f"<div class='gaugebox'>{_gauge(pct, std, own)}</div></section>", unsafe_allow_html=True)


def action_table(table: pd.DataFrame, pick: str) -> None:
    """Every action on the same outcomes, with the recommended row marked."""
    top_e = max(float(table["exposure_index"].max()), 0.01)
    top_s = max(float(table["servings_kept"].max()), 1)

    def bar(v: float, top: float, text: str) -> str:
        return f"<div class='bar'><i style='width:{round(90 * v / top)}px'></i>{text}</div>"

    rows = []
    for r in table.itertuples():
        cls = "pick" if r.action == pick else "" if r.feasible else "no"
        name = escape(r.action) + ("" if r.feasible else " (not possible here)")
        rows.append(f"<tr class='{cls}'><td>{name}</td>"
                    f"<td>{bar(r.exposure_index, top_e, f'{r.exposure_index:.2f}')}</td>"
                    f"<td>{bar(r.servings_kept, top_s, f'{r.servings_kept:,.0f}')}</td>"
                    f"<td class='n'>{r.protein_kg:,.0f}</td><td class='n'>{r.servings_to_need:,.0f}</td>"
                    f"<td class='n'>{r.food_lost_pct:.0f}%</td></tr>")
    st.markdown("<div class='scroll'><table class='acts'><thead><tr><th>Action</th><th>Exposure index</th>"
                "<th>Servings kept</th><th class='n'>Protein kg</th><th class='n'>Servings to need</th>"
                f"<th class='n'>Food lost</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>",
                unsafe_allow_html=True)


__all__ = ["INK", "LEVEL_COLOR", "inject", "brand", "disposition_tag", "action_table"]
