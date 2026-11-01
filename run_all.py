"""Regenerate every result used by the app and report.

Run from the project root:  python run_all.py
"""
from __future__ import annotations

import sys
import time

from scripts import export_web
from src import context, outlook, scenarios, step8_forecast


def main() -> int:
    start = time.time()
    for name, fn in (("1/5 forecast (h=1, best case)", step8_forecast.run),
                     ("2/5 outlook and alert backtest (h=3)", outlook.run),
                     ("3/5 context tables", context.run),
                     ("4/5 scenarios", scenarios.run),
                     ("5/5 web app data", export_web.write)):
        print(f"\n=== {name} ===", flush=True)
        fn()
    print(f"\nDone in {(time.time() - start) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
