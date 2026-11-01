# Structure

- `src/` analysis and decision code. `src/decision/` holds the risk level and action comparison.
- `app/` Streamlit pages. They read `artifacts/` and hold no analysis.
- `data/` public inputs, documented in `DATA_DICTIONARY.md`.
- `tests/` rule, arithmetic and app-load checks.
