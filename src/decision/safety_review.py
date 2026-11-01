"""
Safety review pipeline, from the team's PoultryRescue work.

Implements the required 5-stage workflow with strict honesty guardrails:

  1. PRODUCT CLASSIFICATION   -> Is the product within the NARROW scope of the
     2024 FSIS determination (specified NRTE breaded stuffed chicken products)?
  2. REGULATORY STATUS        -> What currently applies, and is a separate
     threshold SCENARIO being modeled? (enforced_today vs adulterant_framework)
  3. MEASUREMENT INTERPRETATION -> qualitative (detect/not) | reliably QUANTIFIED
     (numeric CFU/g) | CENSORED (e.g. '<10') | UNCERTAIN/none.
  4. SAFETY & ELIGIBILITY REVIEW -> what is required or permissible, and what
     further testing/authorization is necessary.
  5. DISPOSITION OPTIMIZATION  -> among LEGALLY ELIGIBLE pathways, which retains
     the most safe food/protein at reasonable cost.

HARD GUARDRAILS (do not violate):
  * A censored result ('<10') is NOT a quantification; it cannot be placed below
    or at/above 1 CFU/g.
  * A qualitative detect/not-detect is a SCREEN, never a threshold confirmation.
  * 'Not detected' or 'below 1 CFU/g' does NOT mean the lot is CLEAR of all
    hazards/requirements - never auto-clear and never auto-authorize release.
  * The five recovery tiers are POTENTIAL uses, each requiring its own regulatory
    and safety eligibility check - never auto-authorize cooking, animal feed,
    rendering, or disposal from a test result alone.
  * The 2024 determination is NARROWLY scoped to specified NRTE breaded stuffed
    chicken products.
  * Our dataset's data-availability gap is DISTINCT from FSIS's Dec 2 2025
    method-accuracy rationale for delaying enforcement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

# Narrowly-scoped covered products (2024 FSIS final determination).
COVERED_PRODUCTS = {
    "nrte breaded stuffed chicken",
    "raw breaded stuffed chicken",
    "breaded stuffed chicken",
}
ADULTERANT_THRESHOLD_CFU_G = 1.0

# Measurement interpretation classes
M_QUALITATIVE = "qualitative"     # detect / not-detect
M_QUANTIFIED = "quantified"       # a usable numeric CFU/g
M_CENSORED = "censored"           # e.g. '<10' - a limit floor, not a value
M_NONE = "none"                   # no measurement

# Regulatory scenarios
ENFORCED_TODAY = "enforced_today"
ADULTERANT_FRAMEWORK = "adulterant_framework"

# Safety-review statuses (NONE of these authorize release on their own)
POSITIVE_SCREEN_HOLD_CONFIRM = "POSITIVE_SCREEN_HOLD_CONFIRM"
PRESENT_UNQUANTIFIED = "PRESENT_UNQUANTIFIED"
MEASURED_GE_THRESHOLD = "MEASURED_GE_THRESHOLD"
MEASURED_LT_THRESHOLD = "MEASURED_LT_THRESHOLD"
NOT_DETECTED = "NOT_DETECTED"

SCENARIO_NOTES = {
    ENFORCED_TODAY: (
        "Enforced-today: raw/NRTE poultry Salmonella is generally NOT an adulterant. "
        "Diversion to a lethality process is a voluntary food-safety / food-waste "
        "reduction choice, subject to the establishment's HACCP and FSIS oversight."),
    ADULTERANT_FRAMEWORK: (
        "In effect for specified NRTE breaded stuffed chicken only: >=1 CFU/g is an "
        "adulterant (final determination 2024, effective May 2025); FSIS "
        "verification sampling DELAYED (Federal Register 2025-21737, Dec 2025, "
        "citing method-accuracy limits near 1 CFU/g). The broader raw-poultry "
        "framework was WITHDRAWN in April 2025."),
}


@dataclass
class DetectionResult:
    kind: str                         # 'qualitative' or 'quantitative'
    detected: bool | None = None      # qualitative
    cfu_per_g_raw: str | None = None  # quantitative/censored raw token, e.g. '2.3' or '<10'
    source: str = "USER_INPUT"


@dataclass
class ReviewInput:
    product_name: str
    product_category: str
    detection: DetectionResult
    scenario: str = ENFORCED_TODAY


@dataclass
class ReviewOutput:
    is_covered_product: bool
    scenario: str
    scenario_note: str
    measurement_class: str
    measurement_summary: str
    status: str
    status_explanation: str
    required_next_steps: list = field(default_factory=list)
    must_not_enter_commerce_as_is: bool = False
    diversion_permitted: bool = False
    auto_authorized: bool = False     # ALWAYS False - never authorize from a result alone
    labels: dict = field(default_factory=dict)


def classify_product(category: str) -> bool:
    return category.strip().lower() in COVERED_PRODUCTS


def interpret_measurement(det: DetectionResult):
    """Stage 3: classify the measurement honestly. Returns (class, numeric_or_None, summary)."""
    if det.kind == "qualitative":
        if det.detected is True:
            return (M_QUALITATIVE, None,
                    f"Qualitative screen: DETECTED (source: {det.source}). A screen, "
                    f"not a quantification; cannot be placed relative to 1 CFU/g.")
        if det.detected is False:
            return (M_QUALITATIVE, None,
                    f"Qualitative screen: not detected (source: {det.source}). "
                    f"Absence on a screen is not proof of overall safety; other "
                    f"hazards/requirements still apply.")
        return (M_NONE, None, "No qualitative result provided.")
    # quantitative token
    s = (det.cfu_per_g_raw or "").strip()
    if s in ("", "NULL", "None", "nan"):
        return (M_NONE, None, "No quantitative value provided.")
    if s.startswith("<") or s.startswith(">"):
        return (M_CENSORED, None,
                f"Censored value '{s}' (source: {det.source}). A detection/"
                f"quantification-limit floor - NOT a precise concentration; cannot "
                f"be placed below or at/above 1 CFU/g.")
    if re.fullmatch(r"[0-9]+(\.[0-9]+)?", s):
        return (M_QUANTIFIED, float(s),
                f"Quantified: {s} CFU/g (source: {det.source}).")
    return (M_NONE, None, f"Unparseable measurement token '{s}'.")


def review(inp: ReviewInput) -> ReviewOutput:
    covered = classify_product(inp.product_category)
    mclass, numeric, msummary = interpret_measurement(inp.detection)

    steps: list[str] = []
    must_not_commerce = False
    diversion_permitted = False

    # NOT DETECTED (screen negative) - NOT the same as "clear"
    if mclass == M_QUALITATIVE and inp.detection.detected is False:
        status = NOT_DETECTED
        expl = ("Screen negative for Salmonella. This does NOT clear the lot of all "
                "hazards or requirements; routine HACCP controls and any other "
                "applicable verifications still apply. No automatic release.")
        steps = ["Proceed only under normal HACCP controls",
                 "Do not treat a negative screen as proof of overall safety"]
        return _out(covered, inp, mclass, msummary, status, expl, steps,
                    must_not_commerce=False, diversion_permitted=False)

    # Everything below: Salmonella is PRESENT (screen or measurement indicates it)
    present = (
        (mclass == M_QUALITATIVE and inp.detection.detected is True) or
        mclass in (M_QUANTIFIED, M_CENSORED))
    if not present and mclass == M_NONE:
        status = PRESENT_UNQUANTIFIED
        expl = ("No usable result provided; cannot make a disposition decision. "
                "Obtain a valid screen or quantitative test first.")
        steps = ["Obtain a valid Salmonella screen and/or quantitative test"]
        return _out(covered, inp, mclass, msummary, status, expl, steps, False, False)

    # ---- Covered product under the adulterant-framework scenario ----
    if inp.scenario == ADULTERANT_FRAMEWORK and covered:
        if mclass == M_QUANTIFIED and numeric is not None and numeric >= ADULTERANT_THRESHOLD_CFU_G:
            status = MEASURED_GE_THRESHOLD
            expl = (f"Covered product quantified at {numeric} CFU/g "
                    f">= {ADULTERANT_THRESHOLD_CFU_G} CFU/g. Under the modeled "
                    f"framework this would be ADULTERATED and must not enter commerce "
                    f"as-is. Diversion to a hazard-eliminating, separately-authorized "
                    f"process (or disposal) would be required.")
            must_not_commerce = True
            diversion_permitted = True
            steps = ["Hold under establishment control",
                     "Determine a legally eligible, separately-authorized disposition",
                     "Do not release to commerce in adulterated form"]
        elif mclass == M_QUANTIFIED and numeric is not None:
            status = MEASURED_LT_THRESHOLD
            expl = (f"Covered product quantified at {numeric} CFU/g, below the modeled "
                    f">= {ADULTERANT_THRESHOLD_CFU_G} CFU/g threshold. NOT adulterated "
                    f"under this scenario on this basis alone - but this does NOT clear "
                    f"the lot of other hazards/requirements. No automatic release.")
            diversion_permitted = True
            steps = ["Apply all other applicable controls/verifications",
                     "Diversion to lethality permitted as best practice"]
        else:
            # qualitative DETECTED or censored '<10' on a covered product
            status = POSITIVE_SCREEN_HOLD_CONFIRM
            expl = ("Covered product with Salmonella present but NOT reliably "
                    "quantified (qualitative screen or censored value). The >=1 CFU/g "
                    "threshold cannot be established, so hold under establishment "
                    "control pending reliable quantitative confirmation before any "
                    "adulterant determination or commerce. (This measurement gap is "
                    "what rapid validated quantification aims to close.)")
            diversion_permitted = True
            steps = ["Hold under establishment control",
                     "Obtain reliable quantitative confirmation at/around 1 CFU/g",
                     "Do not treat qualitative/censored results as threshold confirmation"]
        return _out(covered, inp, mclass, msummary, status, expl, steps,
                    must_not_commerce, diversion_permitted)

    # ---- Enforced-today, OR not a covered product ----
    status = PRESENT_UNQUANTIFIED
    reason = ("not within the narrow scope of the 2024 determination"
              if not covered else "enforced-today regime (no mandatory adulterant status)")
    expl = (f"Salmonella present. Because this is {reason}, there is no mandatory "
            f"adulterant classification on this basis. Diversion to a validated "
            f"lethality process is PERMITTED as a food-safety / waste-reduction "
            f"choice, but each pathway needs its own eligibility check and no release "
            f"is authorized from the test result alone.")
    diversion_permitted = True
    steps = ["Confirm establishment HACCP handling for a positive raw lot",
             "Evaluate eligible diversion pathways (each needs its own authorization)"]
    return _out(covered, inp, mclass, msummary, status, expl, steps,
                must_not_commerce=False, diversion_permitted=True)


def _out(covered, inp, mclass, msummary, status, expl, steps,
         must_not_commerce, diversion_permitted):
    return ReviewOutput(
        is_covered_product=covered,
        scenario=inp.scenario,
        scenario_note=SCENARIO_NOTES.get(inp.scenario, ""),
        measurement_class=mclass,
        measurement_summary=msummary,
        status=status,
        status_explanation=expl,
        required_next_steps=steps,
        must_not_enter_commerce_as_is=must_not_commerce,
        diversion_permitted=diversion_permitted,
        auto_authorized=False,  # invariant: never authorize from a result alone
        labels={
            "product_category": "USER_INPUT",
            "scenario": "USER_INPUT",
            "detection_source": inp.detection.source,
            "threshold_1cfu_g": ("USDA_REGULATION - 2024 determination, narrowly "
                                  "scoped; enforcement delayed Dec 2 2025"),
        },
    )


def eligible_pathways(out: ReviewOutput, alternatives_df):
    """Stage 5: present the recovery hierarchy as POTENTIAL uses, each flagged as
    requiring its own eligibility check. Ordering favors the most food/protein
    preserved. This function NEVER authorizes a pathway - it ranks candidates."""
    if out.status == NOT_DETECTED:
        return alternatives_df.iloc[0:0]
    df = alternatives_df.sort_values("tier").copy()
    df["eligibility"] = "REQUIRES separate regulatory & safety check (not authorized here)"
    if out.status == POSITIVE_SCREEN_HOLD_CONFIRM:
        # lead with hold/confirm
        lead = df["alternative_id"] == "ALT03"
        df = pd.concat([df[lead], df[~lead]])
    return df
