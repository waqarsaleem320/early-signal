"""Four worked scenarios, each comparing every action on safety and food outcomes.
The lots are illustrative user inputs. Rates, yields and nutrition are measured."""
from __future__ import annotations

import pandas as pd

from . import config
from .decision import actions as A

OUT_DIR = config.PROJECT_ROOT / "artifacts" / "scenarios"

SCENARIOS: dict[str, A.Situation] = {
    "1. Ground chicken, Category 3 line, cooked line available": A.Situation(
        state="MO", month=7, product="Ground chicken", lot_lb=10_000, fsis_category=3,
        has_cooked_line=True),
    "2. Chicken breast, Category 1 line, no cooked line": A.Situation(
        state="MO", month=1, product="Chicken breast", lot_lb=10_000, fsis_category=1),
    "3. Breaded stuffed chicken lot measured at 2.0 CFU/g": A.Situation(
        state="MO", month=4, product="Raw breaded stuffed chicken", lot_lb=5_000,
        has_cooked_line=True, lot_result="detected", cfu_per_g="2.0"),
    "4. Thigh lot, product 6 hours above 40°F after a storm outage": A.Situation(
        state="MO", month=7, product="Chicken thigh", lot_lb=5_000, fsis_category=1,
        has_cooked_line=True, hours_above_40f=6),
}


def run() -> pd.DataFrame:
    """Score every scenario and write the results."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    inp = A.load_inputs()
    frames = []
    for name, s in SCENARIOS.items():
        level, pct, _ = A.risk_level(s, inp)
        pick, why = A.recommend(s, inp)
        t = A.compare_actions(s, inp)
        t.insert(0, "scenario", name)
        t["risk_level"], t["expected_positivity_pct"] = level, pct
        t["recommended"] = t["action"] == pick
        t["why"] = why
        frames.append(t)
    out = pd.concat(frames, ignore_index=True)
    out.to_csv(OUT_DIR / "scenario_results.csv", index=False)
    return out


__all__ = ["SCENARIOS", "run"]
