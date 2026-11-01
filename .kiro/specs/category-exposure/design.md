# Design

- `context._plant_status` rebuilds status per plant line from a 52-week window, 10 or more samples.
- `context.plant_year_pairs` joins status to the next window for three year-pairs.
- `context.category_forward_rates` writes `artifacts/context/category_forward_rates.csv`.
- `context.category_forward_validation` scores a held-out year with the Brier score.
- `context.status_agreement` compares rebuilt status with the published FSIS category through the MPI directory.
- `actions.expected_rate` feeds `risk_level` and `compare_actions`.
- The state outlook is shown as context and does not affect the level.
