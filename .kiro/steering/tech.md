# Tech

- Python 3.11, pandas, statsmodels, Streamlit. Versions are pinned in `requirements.txt`.
- `python run_all.py` rebuilds `artifacts/`. `python -m pytest -q tests` must pass before any commit.
- Validation uses only data known at the forecast or decision time.
- Check food safety claims against 9 CFR 381, 417 and 430 and cite them.
