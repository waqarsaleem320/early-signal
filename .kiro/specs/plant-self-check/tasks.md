# Implementation Plan: Plant Self-Check

## Overview

All self-check logic goes into `src/decision/actions.py` (Python). It covers the exact Fraction boundary rule, the distance to the category actually reached, the messages and the expected-rate precedence. The Dashboard only collects the two counts and renders the `SelfCheck` fields. Hypothesis is not installed and no dependencies are added, so the correctness properties are exhaustive pytest sweeps in `tests/test_decision.py`. Tests run with `.\.venv\Scripts\python.exe -m pytest -q tests`. `src/context.py`, README numbers and everything under `artifacts/` stay unchanged.

## Tasks

- [x] 1. Build the self-check engine in `src/decision/actions.py`
  - [x] 1.1 Add the Situation fields, the SelfCheck type and the exact status rule
    - Add `plant_samples: int = 0` and `plant_positives: int = 0` to `Situation` (defaults keep `src/scenarios.py` and existing tests working)
    - Import `STANDARD_PCT` and `MIN_PLANT_SAMPLES` from `..context`; do not copy them, do not edit `src/context.py`
    - Add the frozen `SelfCheck` dataclass with the fields from the design (`samples`, `positives`, `product_group`, `standard_pct`, `observed_pct`, `status`, `positives_to_next`, `next_status`, `positives_to_drop`, `drop_status`, `message`, `published_note`)
    - Add `SELF_CHECK_NOTE` stating the result is a decision-support self-check and not an FSIS determination
    - Implement `_std` (`Fraction(str(std))`) and `rebuilt_status(positives, samples, standard_pct)` using `200*k <= std*n` → 1, `100*k <= std*n` → 2, else 3; raise `ValueError` for `samples <= 0` or positives outside `[0, samples]`
    - Add `SelfCheck`, `rebuilt_status`, `plant_self_check`, `SELF_CHECK_NOTE`, `STANDARD_PCT`, `MIN_PLANT_SAMPLES` to `__all__`; type-hint everything
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.8_

  - [x]* 1.2 Write property test for the exact status rule
    - **Property 1: Rebuilt status follows the exact FSIS rule**
    - Exhaustive sweep of `rebuilt_status` over the 5 `STANDARD_PCT` groups × n ∈ [10, 400] × k ∈ [0, n] against an independent Fraction reference; cover std/2 → 1 and std → 2
    - The `plant_self_check` half (observed %, standard, status) runs after task 1.4, over the 5 Sidebar products (3 groups)
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.7**

  - [ ]* 1.3 Write property test for agreement with `context._plant_status`
    - **Property 2: Self-check agrees with the published analysis rule**
    - One synthetic DataFrame per group, one synthetic integer establishment ID per (n, k), n ∈ [10, 200]; call `_plant_status` once per group (read only, no edits to `src/context.py`)
    - **Validates: Requirements 2.2, 2.3, 2.4, 2.6, 7.7**

  - [x] 1.4 Implement `_distance` and `plant_self_check`
    - `_distance`: Category 1 → `floor(std·n/200) + 1 − k`; Category 2 → `floor(std·n/100) + 1 − k`; Category 3 → `k − floor(std·n/100)`; return `(count, rebuilt_status(k′, n, std))` so the category actually reached is reported (for the Sidebar products it is always the neighboring category; for the carcass standards at n = 10 it can skip one, which only `_distance` tests reach)
    - Guard `k′ > n`: `positives_to_next = None` and a message saying no change is reachable at this sample count
    - `plant_self_check` check order: n == 0 → `None`; n > 0 with k > n or any count < 0 → status None, "Positives cannot exceed samples" message; 0 < n < `MIN_PLANT_SAMPLES` → status None, too-small message ending "The national rate is used." when `fsis_category` is None, or "The published FSIS Category c drives the expected rate." otherwise; otherwise rebuild status, `observed_pct = float(Fraction(100*k, n))`, distance and message
    - Messages name the category reached (not "the next category"), state "same {n} samples", and include no plant name, outbreak or illness wording
    - Set `published_note` only when `fsis_category` is 1, 2 or 3 and differs from the rebuilt status, naming both categories, the last 52 weeks, and that the published category drives the expected rate
    - Look up the standard via `PRODUCTS[s.product][0]` → `STANDARD_PCT[group]`
    - _Requirements: 2.7, 3.1, 3.2, 3.3, 3.4, 4.1, 4.3, 4.4, 6.2, 6.3, 6.4, 6.5, 6.6, 6.9_

  - [ ]* 1.5 Write property test for distance minimality
    - **Property 3: Distance to the neighboring category is minimal and positive**
    - Sweep `_distance` over the 5 `STANDARD_PCT` groups × n ∈ [10, 400] × k ∈ [0, n]; check d ≥ 1, status changes at k±d, unchanged at one less step (minimal change, not exactly one category), the returned category equals the category reached
    - Sweep `plant_self_check` over the 5 Sidebar products on the same grid; `next_status`/`drop_status` are the neighboring category, and the message contains d, "same {n} samples" and the category reached
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 6.2, 6.3**

  - [ ]* 1.6 Write property test for too-small sample counts
    - **Property 4: Too few samples are flagged and fall back to the national rate**
    - Sweep products × c ∈ {None, 1, 2, 3} × n ∈ [1, MIN_PLANT_SAMPLES − 1] × k ∈ [0, n]; status None, too-small message, and "national rate is used" only when c is None, otherwise the published-category wording (the rate half of this property is checked after task 3.1)
    - **Validates: Requirements 4.1, 4.2, 5.5**

  - [ ]* 1.7 Write property test for invalid counts
    - **Property 5: Invalid counts are rejected and leave the rate unchanged**
    - Sweep products × c ∈ {None, 1, 2, 3} × n ≥ 1 × k > n; status None, "cannot exceed" message, `expected_rate` equal to the 0/0 situation
    - **Validates: Requirements 4.4, 4.5, 5.5**

  - [ ]* 1.8 Write property test for the disagreement note
    - **Property 9: Disagreement note appears exactly when published and rebuilt differ**
    - Sweep products × c ∈ {None, 1, 2, 3} × n ∈ [10, 200] × k ∈ [0, n]; note present iff c is not None and c ≠ r; when present it names both categories, the last 52 weeks and that the published category drives the rate
    - **Validates: Requirements 6.4**

  - [ ]* 1.9 Write property test for message content
    - **Property 10: Messages make no plant, outbreak or illness claim**
    - Over valid, small and invalid grids: no "outbreak" or "illness" in `message`, `published_note` or `SELF_CHECK_NOTE`; `SELF_CHECK_NOTE` says it is not an FSIS determination
    - **Validates: Requirements 6.8, 6.9**

  - [x] 1.10 Write boundary and example unit tests in `tests/test_decision.py`
    - `MIN_PLANT_SAMPLES − 1` samples → no status, too-small message; `MIN_PLANT_SAMPLES` samples → a status
    - Worked boundaries through `plant_self_check`: Chicken parts ("Chicken breast") 77/1000 → 1, 78/1000 → 2, 77/500 → 2, 78/500 → 3; Ground chicken 5/40 → 1, 10/40 → 2. Through `rebuilt_status` with `STANDARD_PCT["Chicken carcass"]` (not a Sidebar group): 49/500 → 2, 49/1000 → 1
    - Distances through `plant_self_check` ("Chicken breast"): 38/500 → 1 more to Category 2; 77/500 → 1 more to Category 3; 100/500 → 23 fewer to Category 2. Turkey carcass jump case through `_distance` directly: 0/10 → 1 more reaches Category 3; 1/10 → 1 fewer reaches Category 1
    - 12 positives of 10 samples → no status; 0 samples → `None`
    - `A.STANDARD_PCT is context.STANDARD_PCT`, `A.MIN_PLANT_SAMPLES == context.MIN_PLANT_SAMPLES`, new names in `A.__all__`
    - _Requirements: 2.5, 2.6, 2.8, 4.3, 7.1, 7.2, 7.3, 7.5_

- [ ] 2. Checkpoint - Ensure all tests pass
  - Run `.\.venv\Scripts\python.exe -m pytest -q tests`. Ensure all tests pass, ask the user if questions arise.

- [x] 3. Apply the self-check to the expected rate
  - [x] 3.1 Update `expected_rate` in `src/decision/actions.py`
    - Published category first (unchanged code path and basis string); then, for "Not listed", use `forward[(group, check.status)]` when `plant_self_check` returns a status, with a basis string saying it uses the status rebuilt from the plant's last 52 weeks of samples; otherwise the national rate
    - Fall back to the national rate if `(group, status)` is missing from the forward table
    - Leave `risk_level` and `compare_actions` unedited; they inherit the rate through `expected_rate`
    - _Requirements: 4.2, 4.3, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ]* 3.2 Write property test for published precedence
    - **Property 6: A published category always wins**
    - Sweep products × c ∈ {1, 2, 3} × n ∈ [0, 200] × k ∈ [0, n + 2]; `expected_rate` equals the n = 0 result, which is `forward[(group, c)]`
    - **Validates: Requirements 5.3, 4.3, 7.4**

  - [ ]* 3.3 Write property test for Not listed using the rebuilt status
    - **Property 7: Not listed uses the rebuilt status for the rate**
    - Sweep products × n ∈ [10, 200] × k ∈ [0, n] with `fsis_category=None`; rate is `forward[(group, status)]` and the basis mentions the rebuilt status from the last 52 weeks; also assert the national rate for the Property 4 small-n grid
    - **Validates: Requirements 5.1, 5.2**

  - [ ]* 3.4 Write property test for downstream consistency
    - **Property 8: risk_level and compare_actions use the chosen rate**
    - Grid over products × c ∈ {None, 1, 2, 3} × records spanning all three categories, small n, invalid counts and n = 0; `risk_level(s)[1] == round(100 * expected_rate(s)[0], 1)` and the "Release raw under normal HACCP" exposure index equals `round(expected_rate(s)[0] / inp["rates"]["Chicken parts"], 2)`
    - **Validates: Requirements 5.4**

  - [x] 3.5 Write precedence and fallback unit tests in `tests/test_decision.py`
    - Published Category 1 with a record that rebuilds to Category 3 → Category 1 forward rate and a non-empty `published_note`
    - 12 of 10 samples → published rate when a category is given, national rate when "Not listed"
    - Small n with "Not listed" → national rate
    - _Requirements: 4.2, 4.5, 7.4, 7.5_

- [ ] 4. Checkpoint - Ensure all tests pass
  - Run `.\.venv\Scripts\python.exe -m pytest -q tests`. Ensure all tests pass, ask the user if questions arise.

- [x] 5. Wire the Dashboard (`app/dashboard.py`, display only)
  - [x] 5.1 Add the sidebar inputs and pass them to `Situation`
    - After the FSIS category selectbox, add a caption and two `st.number_input` fields (min 0, default 0, step 1, keys `plant_samples` and `plant_positives`) labelled "Routine FSIS samples, your plant's last 52 weeks" and "Positives among those samples"
    - Add no new selectbox and keep the existing selectbox order so `tests/test_app.py` indices still hold; no plant name or establishment ID input
    - Pass `plant_samples=int(n_samples), plant_positives=int(n_pos)` into `Situation(...)`; no arithmetic or comparison in the Dashboard
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

  - [x] 5.2 Render the self-check block in Section 1
    - After the reasons list call `A.plant_self_check(s)`; render nothing when it returns `None`
    - Status None → `st.warning(check.message)`; otherwise four metrics (observed %, samples / positives, rebuilt category, FSIS standard), `st.info(check.message)`, and `st.warning(check.published_note)` when set
    - Always end the block with `st.caption(A.SELF_CHECK_NOTE)`; use only `st.info`/`st.warning`/`st.caption`/`st.metric`, never `st.success`, so `app.success[0]` stays the recommendation
    - Update the existing Section 1 caption "An unlisted line uses the national rate." to "An unlisted line uses the national rate, or the category rebuilt from your own samples when you enter at least 10." (display text only, no README change)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10_

  - [ ]* 5.3 Write AppTest smoke test in `tests/test_app.py`
    - Set the two inputs by key (`app.sidebar.number_input(key="plant_samples")`, `key="plant_positives"`; new inputs shift the index-based order) to for example 500 and 100, run, assert no exception, the self-check caption is shown and `app.success[0]` is still the recommendation; follow the existing skip-if-artifacts-missing pattern
    - _Requirements: 1.1, 1.2, 6.1, 6.8, 6.10_

- [ ] 6. Final checkpoint - Ensure all tests pass
  - Run `.\.venv\Scripts\python.exe -m pytest -q tests` and confirm `git diff --stat` shows no change to `src/context.py`, `README.md` or `artifacts/`. Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 7.6, 7.7_

## Notes

- Tasks marked with `*` are optional property and smoke tests and can be skipped for a faster MVP. Tasks 1.10 and 3.5 are not optional because Requirement 7 requires those tests in `tests/test_decision.py`.
- The Sidebar products cover three groups only (Ground chicken, Ground turkey, Chicken parts). For those, the category reached is always the neighboring one (checked exhaustively for n ∈ [10, 400]). It can skip a category only for the carcass standards (for example Turkey or Chicken carcass at n = 10), which are tested through `rebuilt_status` and `_distance` directly. Messages name the category actually reached.
- Do not assert that the expected rate rises with the rebuilt category for Ground turkey: its Category 2 forward rate is below Category 1.
- Properties are exhaustive pytest sweeps, each tagged in its docstring as `Feature: plant-self-check, Property N: ...`. No Hypothesis, no new dependencies.
- Do not change `src/context.py`, README numbers or anything under `artifacts/`. The Dashboard holds no analysis.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.4"] },
    { "id": 2, "tasks": ["1.2", "1.3", "3.1", "5.1"] },
    { "id": 3, "tasks": ["1.5", "5.2"] },
    { "id": 4, "tasks": ["1.6", "5.3"] },
    { "id": 5, "tasks": ["1.7"] },
    { "id": 6, "tasks": ["1.8"] },
    { "id": 7, "tasks": ["1.9"] },
    { "id": 8, "tasks": ["1.10"] },
    { "id": 9, "tasks": ["3.2"] },
    { "id": 10, "tasks": ["3.3"] },
    { "id": 11, "tasks": ["3.4"] },
    { "id": 12, "tasks": ["3.5"] }
  ]
}
```
