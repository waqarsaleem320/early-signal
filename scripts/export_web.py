"""Write web/data.json from artifacts/. run_all.py calls this as its last step."""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import geo, scenarios  # noqa: E402
from src.decision import actions as A  # noqa: E402
from src.decision import yields as Y  # noqa: E402

CTX, OUT = ROOT / "artifacts" / "context", ROOT / "artifacts" / "outlook"


def clean(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records"))


def build() -> dict:
    inp = A.load_inputs()
    products = {}
    for name, (group, fdc, form, note) in A.PRODUCTS.items():
        y = Y.lookup_yield(inp["yields"], form, "roasted")
        products[name] = {"group": group, "note": note, "yield_pct": y.cooking_yield_pct,
                          "protein_g_100g": float(inp["nutrition"].loc[fdc, "protein_g_100g"])}
    need = {}
    for state, g in inp["need"].groupby("state_abbr"):
        top = g.nlargest(5, "need_score")[["county", "need_score", "food_insecure_pct", "svi_overall",
                                           "lila_pop_share", "people_low_income", "food_orgs",
                                           "largest_food_org"]]
        need[state] = clean(top)
    live = pd.read_csv(CTX / "live_outlook.csv")
    live = live.sort_values("period").groupby("state").tail(1)
    storms = pd.read_csv(CTX / "storm_months.csv")
    alerts = pd.read_csv(OUT / "alert_backtest.csv")
    years = pd.read_csv(OUT / "alert_by_year.csv")
    pub = pd.read_csv(CTX / "category_published_rates.csv")
    fwd = pd.read_csv(CTX / "category_forward_rates.csv")
    return {
        "products": products,
        "rates": inp["rates"],
        "fsisStandard": inp["standard"],
        "published": {f"{g}|{c}": v for (g, c), v in inp["published"].items()},
        "forward": {f"{g}|{c}": v for (g, c), v in inp["forward"].items()},
        "stateNames": {s: geo.to_name(s) for s in sorted(live["state"])},
        "live": {r["state"]: r for r in clean(live)},
        "storms": {f"{s}|{m}": int(v) for s, m, v in zip(storms["state"], storms["month"],
                                                         storms["years_with_event"])},
        "need": need,
        "scenarios": {k: dataclasses.asdict(v) for k, v in scenarios.SCENARIOS.items()},
        "evidence": {
            "published": clean(pub),
            "forward": clean(fwd),
            "publishedTest": json.loads((CTX / "category_published_validation.json").read_text()),
            "forwardTest": json.loads((CTX / "category_forward_validation.json").read_text()),
            "agreement": clean(pd.read_csv(CTX / "category_status_agreement.csv")),
            "persistence": clean(pd.read_csv(CTX / "plant_persistence.csv")),
            "accuracy": clean(pd.read_csv(OUT / "accuracy_h3.csv")),
            "alert": clean(alerts[(alerts["target"] == "poultry_serotypes")
                                  & (alerts["rule"] == "forecast_ratio")]),
            "alertYears": clean(years[years["target"] == "poultry_serotypes"]),
        },
    }


def write() -> None:
    (ROOT / "web" / "data.json").write_text(json.dumps(build()), encoding="utf-8")


if __name__ == "__main__":
    write()
