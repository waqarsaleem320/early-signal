"""Decision engine: rank what a processor can do with a lot, and show the trade-off.

Every action reports the same outcomes, so options compare directly:
  exposure_index   raw-handling exposure relative to chicken parts sold raw = 1.0
  servings_kept    3-oz cooked servings still reaching people
  protein_kg       protein in those servings
  servings_to_need servings sent to high-need counties

Servings use one USDA cooking yield for every action, assuming home and plant
cooking lose similar water. Only discard or spoilage loses food.

This is decision support. It authorizes nothing, and it is not a regulatory
determination. A person must review every high-consequence decision.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

import pandas as pd

from .. import config
from ..context import MIN_PLANT_SAMPLES, STANDARD_PCT
from . import safety_review as sr
from . import yields as Y

CONTEXT_DIR = config.PROJECT_ROOT / "artifacts" / "context"
LB_TO_G = 453.592
SERVING_G = 85.0          # 3-oz cooked serving
MAX_HOURS_ABOVE_40F = 2.0 # FSIS consumer guidance; the plant's HACCP critical limit governs
LEVELS = ("Low", "Elevated", "High")

# USER_ASSUMPTION values: the app lets the user change them.
TEST_DETECTION_SHARE = 0.9
DONATED_SHARE = 0.25
HOLD_DAYS = 2

LETHALITY = ("Validated process: 7-log10 Salmonella reduction or equivalent, plus "
             "stabilization (9 CFR 381.150) and Listeria controls for ready-to-eat "
             "product (9 CFR 430), under the plant's HACCP plan")

# product -> (FSIS rate group, FoodData Central id, yield form, note)
PRODUCTS: dict[str, tuple[str, int, str, str]] = {
    "Ground chicken": ("Ground chicken", 171117, "breast",
                       "Cooking yield uses roasted breast as a stand-in; no ground poultry row."),
    "Ground turkey": ("Ground turkey", 171506, "turkey breast",
                      "Cooking yield uses roasted turkey breast as a stand-in."),
    "Chicken breast": ("Chicken parts", 171477, "breast", ""),
    "Chicken thigh": ("Chicken parts", 172388, "thigh", ""),
    "Raw breaded stuffed chicken": ("Chicken parts", 171477, "breast",
                                    "No public rate for this product; chicken parts used as a stand-in."),
}


@dataclass
class Situation:
    """One lot. All fields are entered by the user or read from public context."""
    state: str
    month: int
    product: str
    lot_lb: float
    fsis_category: int | None = None    # 1, 2, 3 or None if not listed
    has_cooked_line: bool = False
    customer_limit: bool = False        # a buyer's specification applies
    lot_result: str = "none"            # none | negative | detected
    cfu_per_g: str | None = None        # quantified result for covered product
    hours_above_40f: float = 0.0        # product temperature, not room air
    max_hours_above_40f: float = MAX_HOURS_ABOVE_40F
    plant_samples: int = 0              # routine FSIS samples, plant's last 52 weeks; 0 = not entered
    plant_positives: int = 0            # Salmonella positives among plant_samples


# Plant self-check: the plant's FSIS category rebuilt from its own routine samples,
# using the per-product standards FSIS verifies under 9 CFR 381 (81 FR 7285, 2016).
SELF_CHECK_NOTE = ("Self-check for decision support, rebuilt from the counts you entered. "
                   "Not an FSIS determination. FSIS uses a count table over a moving 52-week window "
                   "and does not assign a category until it has enough samples. With few samples, "
                   "one positive can move this rebuilt category by a whole step, so treat it as a "
                   "trend, not a status.")


@dataclass(frozen=True)
class SelfCheck:
    """A plant's FSIS category rebuilt from its own last 52 weeks of routine samples.
    Decision support only, not an FSIS determination."""
    samples: int
    positives: int
    product_group: str
    standard_pct: float                 # STANDARD_PCT[product_group]
    observed_pct: float | None          # 100*k/n, None when no status is rebuilt
    status: int | None                  # 1, 2, 3 or None (too small or invalid)
    positives_to_next: int | None       # Category 1 or 2 only
    next_status: int | None             # category reached after positives_to_next more
    positives_to_drop: int | None       # Category 3 only
    drop_status: int | None             # category reached after positives_to_drop fewer
    message: str                        # one plain sentence for Section 1
    published_note: str | None = None   # set only when a published category differs from status


def _std(standard_pct: float | Fraction) -> Fraction:
    """Exact rational of the published standard: Fraction(str(9.8)) == Fraction(49, 5)."""
    return Fraction(str(standard_pct))


def rebuilt_status(positives: int, samples: int, standard_pct: float | Fraction) -> int:
    """FSIS category from counts, exact at the boundaries.
    1 if 100k/n <= std/2, 2 if 100k/n <= std, else 3.
    Requires samples > 0 and 0 <= positives <= samples."""
    if samples <= 0:
        raise ValueError(f"samples must be > 0, got {samples}")
    if positives < 0 or positives > samples:
        raise ValueError(f"positives must be in [0, {samples}], got {positives}")
    std = _std(standard_pct)
    if 200 * positives <= std * samples:
        return 1
    if 100 * positives <= std * samples:
        return 2
    return 3


def _distance(positives: int, samples: int, std: Fraction, status: int) -> tuple[int | None, int | None]:
    """(count, category reached). Category 1/2: fewest added positives that raise the
    category. Category 3: fewest removed positives that bring the line to the standard
    or below. (None, None) when the move needs more positives than samples."""
    if status == 1:
        target = math.floor(std * samples / 200) + 1
    elif status == 2:
        target = math.floor(std * samples / 100) + 1
    else:
        target = math.floor(std * samples / 100)
    if target > samples:
        return None, None
    return abs(target - positives), rebuilt_status(target, samples, std)


def _positives(count: int) -> str:
    return f"{count} positive" if count == 1 else f"{count} positives"


def plant_self_check(s: Situation) -> SelfCheck | None:
    """None when no samples were entered. Otherwise a SelfCheck with a status, or
    with status None and a message saying why (too few samples, or invalid counts)."""
    group = PRODUCTS[s.product][0]
    std_pct = STANDARD_PCT[group]
    n, k = s.plant_samples, s.plant_positives
    if n == 0:
        return None

    def empty(message: str) -> SelfCheck:
        return SelfCheck(samples=n, positives=k, product_group=group, standard_pct=std_pct,
                         observed_pct=None, status=None, positives_to_next=None, next_status=None,
                         positives_to_drop=None, drop_status=None, message=message)

    if n < 0 or k < 0 or k > n:
        return empty("Positives cannot exceed samples, and neither count can be negative. "
                     "Check the counts; the self-check is not used.")
    if n < MIN_PLANT_SAMPLES:
        used = ("The national rate is used." if s.fsis_category is None else
                f"The published FSIS Category {s.fsis_category} drives the expected rate.")
        return empty(f"{n} samples is too small to rebuild a category "
                     f"(at least {MIN_PLANT_SAMPLES} needed). {used}")

    std = _std(std_pct)
    status = rebuilt_status(k, n, std_pct)
    observed = float(Fraction(100 * k, n))
    count, reached = _distance(k, n, std, status)
    head = (f"{k} of {n} samples positive ({observed:.1f}%) against the {std_pct:g}% standard: "
            f"Category {status}.")
    if s.product == "Raw breaded stuffed chicken":
        head = f"No FSIS category exists for this product; chicken parts standard used as a stand-in. {head}"
    to_next = next_status = to_drop = drop_status = None
    if count is None:
        tail = (f"No change in category is reachable at the same {n} samples, "
                "because it would need more positives than samples.")
    elif status in (1, 2):
        to_next, next_status = count, reached
        tail = (f"{_positives(count).replace(' ', ' more ', 1)} at the same {n} samples "
                f"would move the line to Category {reached}.")
    else:
        to_drop, drop_status = count, reached
        tail = (f"{_positives(count).replace(' ', ' fewer ', 1)} at the same {n} samples "
                f"would bring the line to Category {reached} (at or below the standard).")

    note = None
    if s.fsis_category in (1, 2, 3) and s.fsis_category != status:
        note = (f"Your last 52 weeks of samples read Category {status}; "
                f"the published FSIS Category {s.fsis_category} drives the expected rate, "
                f"so the risk shown may be {'lower' if status > s.fsis_category else 'higher'} "
                "than your own samples suggest.")
    return SelfCheck(samples=n, positives=k, product_group=group, standard_pct=std_pct,
                     observed_pct=observed, status=status, positives_to_next=to_next,
                     next_status=next_status, positives_to_drop=to_drop, drop_status=drop_status,
                     message=f"{head} {tail}", published_note=note)


def load_inputs() -> dict:
    """Load the measured tables the engine needs."""
    rates = pd.read_csv(CONTEXT_DIR / "product_rates.csv")
    r = rates.groupby("product_group")[["positives", "samples"]].sum()
    f = pd.read_csv(CONTEXT_DIR / "category_forward_rates.csv")
    pub = pd.read_csv(CONTEXT_DIR / "category_published_rates.csv")
    return {"rates": (r["positives"] / r["samples"]).to_dict(),
            "forward": {(g, c): k / n for g, c, k, n in zip(f["product_group"], f["category"],
                                                            f["positives"], f["samples"])},
            "published": {(g, c): k / n for g, c, k, n in zip(pub["product_group"], pub["category"],
                                                              pub["positives"], pub["samples"])},
            "standard": f.groupby("product_group")["fsis_standard_pct"].first().to_dict(),
            "yields": pd.read_csv(config.DATA_DIR / "cooking_yields_poultry.csv"),
            "nutrition": pd.read_csv(config.DATA_DIR / "fdc_poultry_nutrition_pinned.csv").set_index("fdcId"),
            "need": pd.read_csv(CONTEXT_DIR / "county_need.csv", dtype={"fips": str})}


def expected_rate(s: Situation, inp: dict) -> tuple[float, str]:
    """Share of samples expected positive, and where the number came from.
    A published FSIS category always wins. With none, a category rebuilt from the
    plant's own last 52 weeks of samples is used. Otherwise the national rate."""
    group = PRODUCTS[s.product][0]
    if s.fsis_category is not None:
        rate = inp["published"].get((group, s.fsis_category))
        if rate is not None:
            return rate, f"published Category {s.fsis_category} {group.lower()} lines, the following year"
        return inp["rates"][group], f"national {group.lower()} rate"
    check = plant_self_check(s)
    if check is not None and check.status is not None:
        rate = inp["forward"].get((group, check.status))
        if rate is not None:
            return rate, (f"Category {check.status} {group.lower()} lines, the following year, "
                          "using the status rebuilt from your plant's last 52 weeks of samples")
    return inp["rates"][group], f"national {group.lower()} rate"


def risk_level(s: Situation, inp: dict) -> tuple[str, float, list[str]]:
    """Level from expected positivity against the FSIS standard: at or below half
    is Low, above half is Elevated, above the standard is High. A positive screen
    or a buyer's specification raises it one step."""
    rate, basis = expected_rate(s, inp)
    pct = 100 * rate
    std = inp["standard"][PRODUCTS[s.product][0]]
    step = int(pct > std / 2) + int(pct > std)
    why = [f"Expected positivity {pct:.1f}% ({basis}); FSIS standard {std:g}%"]
    check = plant_self_check(s)
    if s.fsis_category and check and check.status and check.status > s.fsis_category:
        step += 1
        why.append(f"Your own samples read Category {check.status}, worse than the published "
                   f"Category {s.fsis_category} (up one level)")
    if s.lot_result == "detected":
        step += 1
        why.append("Lot screen detected Salmonella (up one level)")
    if s.customer_limit:
        step += 1
        why.append("A buyer's specification applies (up one level)")
    review = _review(s)
    if s.hours_above_40f >= s.max_hours_above_40f:
        step = 2
        why.append(f"Product at {s.max_hours_above_40f:g} hours or more above 40°F (High)")
    if review and review.must_not_enter_commerce_as_is:
        step = 2
        why.append("Covered product measured at or above 1 CFU/g (High)")
    elif _hold(review):
        step = 2
        why.append("Covered product screened positive, hold for a quantified result (High)")
    elif review and review.measurement_class in (sr.M_QUANTIFIED, sr.M_CENSORED):
        step += 1
        why.append("Salmonella counted in a covered product, below 1 CFU/g (up one level)")
    elif s.cfu_per_g and review and review.measurement_class == sr.M_NONE:
        why.append("The CFU/g value could not be read. Enter a number")
    return LEVELS[min(step, 2)], round(pct, 1), why


def _review(s: Situation) -> sr.ReviewOutput | None:
    """Safety review, used for the product covered by the 2024 determination."""
    if s.product != "Raw breaded stuffed chicken" or (s.lot_result == "none" and not s.cfu_per_g):
        return None
    if s.cfu_per_g:
        det = sr.DetectionResult(kind="quantitative", cfu_per_g_raw=s.cfu_per_g)
    else:
        det = sr.DetectionResult(kind="qualitative", detected=s.lot_result == "detected")
    return sr.review(sr.ReviewInput(s.product, "raw breaded stuffed chicken", det,
                                    sr.ADULTERANT_FRAMEWORK))


def _hold(review: sr.ReviewOutput | None) -> bool:
    """True when a covered product must wait for a quantified result."""
    return bool(review and review.status == sr.POSITIVE_SCREEN_HOLD_CONFIRM)


def _servings(s: Situation, inp: dict) -> tuple[float, float, dict]:
    """Cooked servings and protein if the whole lot is eaten."""
    _, fdc, form, note = PRODUCTS[s.product]
    y = Y.lookup_yield(inp["yields"], form, "roasted")
    cooked_g = s.lot_lb * LB_TO_G * y.cooking_yield_pct / 100
    protein_kg = cooked_g * float(inp["nutrition"].loc[fdc, "protein_g_100g"]) / 100 / 1000
    return cooked_g / SERVING_G, protein_kg, {"yield_pct": y.cooking_yield_pct, "yield_note": note,
                                              "yield_match": y.match_quality}


def compare_actions(s: Situation, inp: dict, test_detection: float = TEST_DETECTION_SHARE,
                    donated_share: float = DONATED_SHARE) -> pd.DataFrame:
    """All actions with the same outcome columns, marked feasible or not."""
    base = expected_rate(s, inp)[0] / inp["rates"]["Chicken parts"]
    servings, protein, _ = _servings(s, inp)
    review = _review(s)
    in_limit = s.hours_above_40f < s.max_hours_above_40f
    adulterated = bool(review and review.must_not_enter_commerce_as_is)
    hold = _hold(review)
    blocked_raw = not in_limit or adulterated or hold
    line = s.has_cooked_line

    def row(name, remaining, kept, need, feasible, note):
        return {"action": name, "feasible": feasible, "exposure_index": round(base * remaining, 2),
                "servings_kept": round(servings * kept), "protein_kg": round(protein * kept, 1),
                "servings_to_need": round(servings * need) if feasible else 0, "food_lost_pct": round(100 * (1 - kept), 1),
                "note": note}

    rows = [
        row("Release raw under normal HACCP", 1, 1, 0, not blocked_raw,
            "Normal route. Raw poultry is cooked by the end user."),
        row("Release raw, add verification", 1, 1, 0, not blocked_raw,
            "More sampling and intervention checks. Exposure effect not estimated."),
        row("Hold and test, cook any positives", 1 - test_detection, 1, 0,
            in_limit and not adulterated and (line or hold),
            f"About {HOLD_DAYS} days of shelf life used (placeholder). Assumes the test finds "
            f"{test_detection:.0%} of positive lots. A large lot is more likely to contain "
            "Salmonella than one sample suggests."),
        row("Redirect to validated cooked line", 0, 1, 0, line and in_limit, LETHALITY),
        row("Redirect to cooked line, donate part", 0, 1, donated_share,
            line and in_limit,
            f"{donated_share:.0%} donated after a validated cook. {LETHALITY}"),
        row("Discard or render", 0, 0, 0, True, "Last resort. No food kept."),
    ]
    return pd.DataFrame(rows)


def recommend(s: Situation, inp: dict) -> tuple[str, str]:
    """Pick one action and say why."""
    level = risk_level(s, inp)[0]
    review = _review(s)
    if s.hours_above_40f >= s.max_hours_above_40f:
        return "Discard or render", (f"Product exceeded the {s.max_hours_above_40f:g}-hour limit above 40°F. "
                                     "Two hours is FSIS consumer guidance; the critical limit in the "
                                     "plant's HACCP plan (9 CFR 417.2) governs. Cooking kills Salmonella, "
                                     "but it does not address toxins from other bacteria or lost "
                                     "HACCP control. The plant's process authority makes the final call.")
    if review and review.must_not_enter_commerce_as_is:
        action = "Redirect to validated cooked line" if s.has_cooked_line else "Discard or render"
        return action, review.status_explanation
    if _hold(review):
        return "Hold and test, cook any positives", review.status_explanation
    if level == "High":
        if s.has_cooked_line:
            return "Redirect to cooked line, donate part", "High risk and a cooked line is available."
        return "Release raw, add verification", ("High risk, but this plant has no cooked line. "
                                                 "Raw poultry is generally not adulterated, so verify and "
                                                 "consider a co-packer.")
    if level == "Elevated":
        return "Release raw, add verification", "Elevated risk. See the reasons below."
    return "Release raw under normal HACCP", "Low risk."


def donation_targets(state: str, need: pd.DataFrame, servings: float, top: int = 5) -> pd.DataFrame:
    """Highest-need counties in the plant's state, for the donated servings."""
    d = need[need["state_abbr"] == state].nlargest(top, "need_score").copy()
    weight = d["people_low_income"] / d["people_low_income"].sum()
    d["servings"] = (weight * servings).round()
    return d[["county", "need_score", "food_insecure_pct", "svi_overall", "lila_pop_share",
              "people_low_income", "food_orgs", "largest_food_org", "servings"]]


__all__ = ["PRODUCTS", "Situation", "load_inputs", "expected_rate", "risk_level", "compare_actions", "recommend",
           "donation_targets", "MAX_HOURS_ABOVE_40F", "TEST_DETECTION_SHARE", "DONATED_SHARE",
           "SelfCheck", "rebuilt_status", "plant_self_check", "SELF_CHECK_NOTE", "STANDARD_PCT",
           "MIN_PLANT_SAMPLES"]
