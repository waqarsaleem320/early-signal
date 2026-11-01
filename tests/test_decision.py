"""Checks that fail if the safety rules or arithmetic break."""
import pandas as pd
import pytest

from src import context, geo
from src.decision import actions as A
from src.decision import safety_review as sr


@pytest.fixture(scope="module")
def inp():
    return A.load_inputs()


def lot(**kw):
    base = dict(state="MO", month=7, product="Chicken breast", lot_lb=1000)
    return A.Situation(**(base | kw))


def test_dc_name_maps():
    assert geo.to_abbr("DISTRICT OF COLUMBIA") == "DC"


def test_wilson_contains_rate():
    lo, hi = context.wilson([50], [100])
    assert lo[0] < 0.5 < hi[0]


def test_low_risk_released(inp):
    assert A.recommend(lot(fsis_category=1), inp)[0] == "Release raw under normal HACCP"


def test_high_risk_with_line_redirects(inp):
    s = lot(product="Ground chicken", fsis_category=3, has_cooked_line=True)
    assert A.risk_level(s, inp)[0] == "High"
    assert A.recommend(s, inp)[0] == "Redirect to cooked line, donate part"


def test_no_cooked_line_never_recommends_cooking(inp):
    s = lot(product="Ground chicken", fsis_category=3)
    pick = A.recommend(s, inp)[0]
    assert "cooked" not in pick.lower()
    t = A.compare_actions(s, inp).set_index("action")
    assert not t.loc["Redirect to validated cooked line", "feasible"]


def test_temperature_abuse_is_not_cooked_away(inp):
    s = lot(has_cooked_line=True, hours_above_40f=6)
    assert A.recommend(s, inp)[0] == "Discard or render"
    t = A.compare_actions(s, inp).set_index("action")
    assert not t.loc["Release raw under normal HACCP", "feasible"]
    assert not t.loc["Redirect to validated cooked line", "feasible"]


def test_covered_product_above_threshold_blocked(inp):
    s = lot(product="Raw breaded stuffed chicken", has_cooked_line=True,
            lot_result="detected", cfu_per_g="2.0")
    t = A.compare_actions(s, inp).set_index("action")
    assert not t.loc["Release raw under normal HACCP", "feasible"]
    assert A.recommend(s, inp)[0] == "Redirect to validated cooked line"


@pytest.mark.parametrize("kw", [dict(lot_result="detected"), dict(cfu_per_g="<10")])
@pytest.mark.parametrize("line", [True, False])
def test_covered_screen_positive_is_held_not_released(inp, kw, line):
    s = lot(product="Raw breaded stuffed chicken", has_cooked_line=line, **kw)
    assert A.recommend(s, inp)[0] == "Hold and test, cook any positives"
    t = A.compare_actions(s, inp).set_index("action")
    assert not t.loc["Release raw under normal HACCP", "feasible"]
    assert t.loc["Hold and test, cook any positives", "feasible"]


def test_lower_bound_at_threshold_is_adulterated():
    det = sr.DetectionResult(kind="quantitative", cfu_per_g_raw=">5")
    r = sr.review(sr.ReviewInput("x", "raw breaded stuffed chicken", det, sr.ADULTERANT_FRAMEWORK))
    assert r.must_not_enter_commerce_as_is


def test_censored_value_is_not_quantified():
    r = sr.review(sr.ReviewInput("x", "raw breaded stuffed chicken",
                                 sr.DetectionResult(kind="quantitative", cfu_per_g_raw="<10"),
                                 sr.ADULTERANT_FRAMEWORK))
    assert r.measurement_class == sr.M_CENSORED
    assert r.auto_authorized is False


def test_outcomes_consistent(inp):
    t = A.compare_actions(lot(has_cooked_line=True, lot_lb=1000), inp).set_index("action")
    assert t.loc["Discard or render", "servings_kept"] == 0
    assert t.loc["Redirect to validated cooked line", "exposure_index"] == 0
    assert t.loc["Release raw under normal HACCP", "exposure_index"] == 1
    # 1,000 lb at 72% yield is 8,163.1 g x 100 ... about 3,842 3-oz servings
    assert t.loc["Release raw under normal HACCP", "servings_kept"] == pytest.approx(3842, abs=2)
    assert t.loc["Redirect to cooked line, donate part", "servings_to_need"] == pytest.approx(960, abs=2)


def test_protein_uses_real_breast(inp):
    assert inp["nutrition"].loc[171477, "protein_g_100g"] == pytest.approx(31.02)


def test_lethality_text_is_7_log():
    assert "7-log10" in A.LETHALITY


def test_donation_splits_servings(inp):
    d = A.donation_targets("MO", inp["need"], 1000)
    assert len(d) == 5
    assert d["servings"].sum() == pytest.approx(1000, abs=3)
    assert isinstance(d, pd.DataFrame)


def test_need_score_keeps_counties_without_food_insecurity(inp):
    n = inp["need"]
    assert n["food_insecure_pct"].notna().any() and n["food_insecure_pct"].isna().any()
    assert n["need_score"].between(0, 1).all()


def test_published_category_uses_published_rate(inp):
    rate = A.expected_rate(lot(product="Ground chicken", fsis_category=3), inp)[0]
    assert rate == inp["published"][("Ground chicken", 3)]


def test_published_note_direction(inp):
    worse = lot(fsis_category=1, plant_samples=40, plant_positives=11)
    better = lot(fsis_category=3, plant_samples=40, plant_positives=0)
    assert "may be lower" in A.plant_self_check(worse).published_note
    assert "may be higher" in A.plant_self_check(better).published_note


def test_infeasible_action_sends_no_servings(inp):
    t = A.compare_actions(lot(), inp).set_index("action")
    assert t.loc["Redirect to cooked line, donate part", "servings_to_need"] == 0


def test_hold_and_test_removes_found_positives(inp):
    s = lot(product="Ground chicken", has_cooked_line=True)
    t = A.compare_actions(s, inp, test_detection=0.9).set_index("action")
    raw = t.loc["Release raw under normal HACCP", "exposure_index"]
    assert t.loc["Hold and test, cook any positives", "exposure_index"] == pytest.approx(raw * 0.1, abs=0.01)


def test_two_hour_rule_blocks_raw_release(inp):
    assert A.recommend(lot(has_cooked_line=True, hours_above_40f=2), inp)[0] == "Discard or render"


def test_haccp_limit_overrides_default(inp):
    s = lot(fsis_category=1, hours_above_40f=2, max_hours_above_40f=4)
    assert A.recommend(s, inp)[0] != "Discard or render"


@pytest.mark.parametrize("product", ["Ground chicken", "Chicken breast"])
def test_exposure_rises_with_category(inp, product):
    raw = [A.compare_actions(lot(product=product, fsis_category=c), inp)["exposure_index"].iloc[0]
           for c in (1, 2, 3)]
    assert raw[0] < raw[1] < raw[2]


def test_status_follows_fsis_definition():
    d = pd.DataFrame({"establishment_id": [1] * 20 + [2] * 20 + [3] * 20,
                      "product_group": "Chicken parts",
                      "collection_date": pd.Timestamp("2025-01-01"),
                      "positive": [True] * 1 + [False] * 19 + [True] * 2 + [False] * 18
                      + [True] * 4 + [False] * 16})
    g = context._plant_status(d, pd.Timestamp("2024-01-01"), pd.Timestamp("2026-01-01"))
    assert g["status"].tolist() == [1, 2, 3]   # 5%, 10%, 20% against 15.4%


# --- Plant self-check -------------------------------------------------------

SIDEBAR_PRODUCTS = list(A.PRODUCTS)


def _ref_std(std: float) -> tuple[int, int]:
    """Standard as an exact integer ratio p/q, built through Decimal, not A._std."""
    from decimal import Decimal
    from fractions import Fraction
    f = Fraction(Decimal(repr(std)))
    return f.numerator, f.denominator


def _ref_status(k: int, n: int, p: int, q: int) -> int:
    """Independent exact reference in integers: 100k/n <= (p/q)/2 -> 1, <= p/q -> 2, else 3."""
    if 200 * k * q <= p * n:
        return 1
    if 100 * k * q <= p * n:
        return 2
    return 3


def test_status_follows_exact_rule():
    """Feature: plant-self-check, Property 1: Rebuilt status follows the exact FSIS rule.
    rebuilt_status half: every STANDARD_PCT group, n in [MIN_PLANT_SAMPLES, 400], k in [0, n].

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.7**"""
    assert len(A.STANDARD_PCT) == 5
    at_half = at_std = 0
    for group, std in A.STANDARD_PCT.items():
        p, q = _ref_std(std)
        for n in range(A.MIN_PLANT_SAMPLES, 401):
            for k in range(n + 1):
                got = A.rebuilt_status(k, n, std)
                assert got == _ref_status(k, n, p, q), (group, n, k)
                if 200 * k * q == p * n:          # observed exactly std/2
                    at_half += 1
                    assert got == 1, (group, n, k)
                elif 100 * k * q == p * n:        # observed exactly std
                    at_std += 1
                    assert got == 2, (group, n, k)
    # The sweep really reaches both exact boundaries.
    assert at_half > 0 and at_std > 0


def test_self_check_reports_exact_status():
    """Feature: plant-self-check, Property 1: Rebuilt status follows the exact FSIS rule.
    plant_self_check half: the 5 Sidebar products (3 groups), n in [MIN_PLANT_SAMPLES, 200],
    k in [0, n]; observed percent, standard and status. (rebuilt_status itself is swept
    to n = 400 above; this half builds a full SelfCheck per case, so it stops at 200.)

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.7**"""
    from fractions import Fraction
    assert len(SIDEBAR_PRODUCTS) == 5
    assert len({A.PRODUCTS[p][0] for p in SIDEBAR_PRODUCTS}) == 3
    for product in SIDEBAR_PRODUCTS:
        group = A.PRODUCTS[product][0]
        std = A.STANDARD_PCT[group]
        p, q = _ref_std(std)
        s = lot(product=product, fsis_category=None)
        for n in range(A.MIN_PLANT_SAMPLES, 201):
            s.plant_samples = n
            for k in range(n + 1):
                s.plant_positives = k
                c = A.plant_self_check(s)
                assert c is not None and c.product_group == group
                assert c.samples == n and c.positives == k
                assert c.standard_pct == std
                assert c.observed_pct == float(Fraction(100 * k, n))
                assert c.observed_pct == pytest.approx(100 * k / n)
                assert c.status == _ref_status(k, n, p, q), (product, n, k)


def _check(n: int, k: int, product: str = "Chicken breast", **kw) -> "A.SelfCheck | None":
    return A.plant_self_check(lot(product=product, plant_samples=n, plant_positives=k, **kw))


def test_self_check_minimum_samples_boundary(inp):
    """Requirements 4.1, 4.2, 7.1: one below the minimum gives no status; the minimum gives one."""
    small = _check(A.MIN_PLANT_SAMPLES - 1, 0)
    assert small is not None and small.status is None and small.observed_pct is None
    assert "too small" in small.message and str(A.MIN_PLANT_SAMPLES) in small.message
    assert "national rate is used" in small.message
    s = lot(plant_samples=A.MIN_PLANT_SAMPLES - 1, plant_positives=0)
    assert A.expected_rate(s, inp)[0] == inp["rates"]["Chicken parts"]
    at_min = _check(A.MIN_PLANT_SAMPLES, 0)
    assert at_min is not None and at_min.status == 1


@pytest.mark.parametrize("product,n,k,status", [
    # Chicken parts 15.4%: half = 7.7%
    ("Chicken breast", 1000, 77, 1),   # exactly std/2
    ("Chicken breast", 1000, 78, 2),   # one above std/2
    ("Chicken breast", 500, 77, 2),    # exactly std
    ("Chicken breast", 500, 78, 3),    # one above std
    # Ground chicken 25.0%
    ("Ground chicken", 40, 5, 1),      # 12.5% = std/2
    ("Ground chicken", 40, 10, 2),     # 25.0% = std
])
def test_self_check_exact_boundaries(product, n, k, status):
    """Requirements 2.5, 7.2: boundaries are exact, at std/2 -> 1 and at std -> 2."""
    c = _check(n, k, product)
    assert c is not None and c.status == status


def test_rebuilt_status_chicken_carcass_boundaries():
    """Requirements 2.5, 7.2: Chicken carcass 9.8% (not a Sidebar group), where 9.8 is inexact in binary."""
    std = A.STANDARD_PCT["Chicken carcass"]
    assert A.rebuilt_status(49, 500, std) == 2    # 9.8% = std
    assert A.rebuilt_status(49, 1000, std) == 1   # 4.9% = std/2


def test_self_check_distances():
    """Requirements 7.3: Positives_To_Next for Categories 1 and 2, Positives_To_Drop for 3."""
    c1 = _check(500, 38)                          # 7.6% <= 7.7%
    assert c1.status == 1
    assert (c1.positives_to_next, c1.next_status) == (1, 2)
    assert c1.positives_to_drop is None and c1.drop_status is None
    assert "1 more positive at the same 500 samples" in c1.message

    c2 = _check(500, 77)                          # 15.4% = std
    assert c2.status == 2
    assert (c2.positives_to_next, c2.next_status) == (1, 3)
    assert c2.positives_to_drop is None

    c3 = _check(500, 100)                         # 20.0% > std; 77 is the most at or below
    assert c3.status == 3
    assert (c3.positives_to_drop, c3.drop_status) == (23, 2)
    assert c3.positives_to_next is None and c3.next_status is None
    assert "23 fewer positives at the same 500 samples" in c3.message


def test_distance_turkey_carcass_jumps():
    """Requirements 7.3: at 10 samples and 7.1%, one positive is above the standard, so a
    single move jumps between Categories 1 and 3."""
    std = A._std(A.STANDARD_PCT["Turkey carcass"])
    assert A.rebuilt_status(0, 10, std) == 1
    assert A._distance(0, 10, std, 1) == (1, 3)
    assert A.rebuilt_status(1, 10, std) == 3
    assert A._distance(1, 10, std, 3) == (1, 1)


def test_self_check_invalid_and_not_entered(inp):
    """Requirements 4.3, 4.4, 7.5: positives above samples give no status; 0 samples gives None."""
    bad = _check(10, 12)
    assert bad is not None and bad.status is None and bad.observed_pct is None
    assert "cannot exceed" in bad.message
    assert _check(0, 0) is None
    assert _check(0, 5) is None
    assert A.expected_rate(lot(plant_samples=0, plant_positives=5), inp) == A.expected_rate(lot(), inp)


def test_self_check_reads_context_constants():
    """Requirements 2.6, 2.8: constants come from src/context.py and the API is exported."""
    assert A.STANDARD_PCT is context.STANDARD_PCT
    assert A.MIN_PLANT_SAMPLES == context.MIN_PLANT_SAMPLES
    for name in ("SelfCheck", "rebuilt_status", "plant_self_check", "SELF_CHECK_NOTE",
                 "STANDARD_PCT", "MIN_PLANT_SAMPLES"):
        assert name in A.__all__, name


def test_published_category_wins_over_rebuilt(inp):
    """Requirements 4.5, 7.4: a published Category 1 drives the rate even when the
    record rebuilds to Category 3, and the published note names both."""
    s = lot(fsis_category=1, plant_samples=500, plant_positives=100)   # 20.0% -> Category 3
    c = A.plant_self_check(s)
    assert c is not None and c.status == 3
    assert A.expected_rate(s, inp)[0] == inp["published"][("Chicken parts", 1)]
    assert c.published_note
    assert "Category 3" in c.published_note and "Category 1" in c.published_note


@pytest.mark.parametrize("category", [1, 2, 3])
def test_invalid_counts_fall_back_to_published(inp, category):
    """Requirements 4.5, 7.5: 12 of 10 samples gives the published rate when a category is given."""
    s = lot(fsis_category=category, plant_samples=10, plant_positives=12)
    assert A.expected_rate(s, inp)[0] == inp["published"][("Chicken parts", category)]


def test_invalid_counts_not_listed_use_national(inp):
    """Requirements 4.2, 7.5: 12 of 10 samples with "Not listed" gives the national rate."""
    s = lot(plant_samples=10, plant_positives=12)
    assert A.expected_rate(s, inp)[0] == inp["rates"]["Chicken parts"]


def test_small_sample_not_listed_uses_national(inp):
    """Requirements 4.2: fewer than MIN_PLANT_SAMPLES with "Not listed" gives the national rate."""
    s = lot(plant_samples=A.MIN_PLANT_SAMPLES - 1, plant_positives=3)
    rate, basis = A.expected_rate(s, inp)
    assert rate == inp["rates"]["Chicken parts"]
    assert "national" in basis


def test_not_listed_uses_rebuilt_status(inp):
    """Requirements 4.2, 7.4: with "Not listed" and n >= MIN_PLANT_SAMPLES, the rebuilt
    status selects the forward rate and the basis says so."""
    s = lot(plant_samples=500, plant_positives=100)                    # rebuilds to Category 3
    c = A.plant_self_check(s)
    assert c is not None and c.status == 3 and c.published_note is None
    rate, basis = A.expected_rate(s, inp)
    assert rate == inp["forward"][("Chicken parts", c.status)]
    assert "rebuilt" in basis and "52 weeks" in basis


def test_worse_own_samples_raise_level_but_keep_published_rate(inp):
    s = lot(fsis_category=1, plant_samples=40, plant_positives=11)
    base = lot(fsis_category=1)
    assert A.risk_level(base, inp)[0] == "Low"
    assert A.risk_level(s, inp)[0] == "Elevated"
    assert A.expected_rate(s, inp) == A.expected_rate(base, inp)


def test_stand_in_product_says_no_fsis_category():
    s = lot(product="Raw breaded stuffed chicken", plant_samples=20, plant_positives=3)
    assert "No FSIS category exists" in A.plant_self_check(s).message
