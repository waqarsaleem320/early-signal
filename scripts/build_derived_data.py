"""Rebuild the small derived input files in data/. Not needed to run the project.

    python scripts/build_derived_data.py nutrition
    python scripts/build_derived_data.py food_access "path/to/Food Access Research Atlas.csv"
    python scripts/build_derived_data.py recalls path/to/fsis_recalls_api.json

fsis_recalls_api.json is the JSON from https://www.fsis.usda.gov/fsis/api/recall/v/1,
saved from a browser, because that site refuses scripted requests.
Set FDC_API_KEY for nutrition; otherwise the public DEMO_KEY is used.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import urllib.request
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parents[1] / "data"
FDC_IDS = (171054, 171117, 171477, 172380, 172388, 171506)


def nutrition() -> None:
    key = os.getenv("FDC_API_KEY", "DEMO_KEY")
    with open(DATA / "fdc_poultry_nutrition_pinned.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["fdcId", "description", "dataType", "protein_g_100g", "fat_g_100g",
                    "water_g_100g", "sodium_mg_100g", "energy_kcal_100g"])
        for i in FDC_IDS:
            url = f"https://api.nal.usda.gov/fdc/v1/food/{i}?api_key={key}"
            d = json.load(urllib.request.urlopen(url, timeout=30))

            def g(name: str, unit: str | None = None):
                return next((x.get("amount") for x in d["foodNutrients"]
                             if x["nutrient"]["name"] == name
                             and (unit is None or x["nutrient"].get("unitName", "").lower() == unit)), None)

            w.writerow([d["fdcId"], d["description"], d["dataType"], g("Protein"), g("Total lipid (fat)"),
                        g("Water"), g("Sodium, Na"), g("Energy", "kcal")])


def food_access(path: str) -> None:
    d = pd.read_csv(path, usecols=["CensusTract", "State", "County", "Pop2010", "LILATracts_1And10"],
                    low_memory=False)
    d["fips"] = d["CensusTract"].astype(str).str.zfill(11).str[:5]
    d["lila_pop"] = d["Pop2010"] * d["LILATracts_1And10"]
    g = d.groupby("fips").agg(state=("State", "first"), county=("County", "first"),
                              pop2010=("Pop2010", "sum"), lila_pop=("lila_pop", "sum")).reset_index()
    g["lila_pop_share"] = (g["lila_pop"] / g["pop2010"]).round(4)
    g.to_csv(DATA / "county_food_access_2019.csv", index=False)


def recalls(path: str) -> None:
    d = pd.DataFrame(json.load(open(path, encoding="utf-8")))
    d = d[d["langcode"] == "English"].copy()

    def text(col: str) -> pd.Series:
        return d[col].map(lambda v: " ".join(map(str, v)) if isinstance(v, list) else ("" if v is None else str(v)))

    cols = ["field_recall_number", "field_recall_date", "field_recall_type", "field_recall_classification",
            "field_recall_reason", "field_risk_level", "field_title", "field_establishment", "field_states",
            "field_qty_recovered", "field_product_items", "field_related_to_outbreak", "field_recall_url"]
    out = pd.DataFrame({c: text(c) for c in cols})
    full = (text("field_title") + " " + text("field_summary") + " " + text("field_product_items")).str.lower()
    head = (text("field_title") + " " + text("field_product_items")).str.lower()
    out["poultry"] = head.str.contains("chicken|turkey|poultry")
    out["salmonella"] = full.str.contains("salmonella")
    out["listeria"] = full.str.contains("listeria")
    out.to_csv(DATA / "fsis_recalls_2014_2026.csv", index=False)


if __name__ == "__main__":
    task = sys.argv[1]
    if task == "nutrition":
        nutrition()
    elif task == "food_access":
        food_access(sys.argv[2])
    elif task == "recalls":
        recalls(sys.argv[2])
    else:
        raise SystemExit(__doc__)
