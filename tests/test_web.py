"""The web app must give the same answers as the Python engine."""
import itertools
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import export_web
from src.decision import actions as A

ROOT = Path(__file__).resolve().parents[1]
CHECK = """
import {readFileSync} from "node:fs";
import * as E from "%s";
const {data, cases} = JSON.parse(readFileSync(process.argv[2], "utf8"));
let bad = 0;
for (const c of cases) {
  const r = E.riskLevel(c.s, data), [pick, why] = E.recommend(c.s, data);
  const t = E.compareActions(c.s, data);
  const sc = E.selfCheck(c.s, data);
  const same = r.level === c.level && Math.abs(r.pct - c.pct) < 1e-9 && r.why.join("|") === c.why.join("|")
    && pick === c.pick && why === c.reason && (sc ? sc.message : null) === c.message
    && (sc ? sc.published_note : null) === c.note
    && JSON.stringify(t.map(x => [x.action, x.feasible, x.servings_kept, x.servings_to_need, x.note]))
       === JSON.stringify(c.table.map(x => [x.action, x.feasible, x.servings_kept, x.servings_to_need, x.note]))
    && t.every((x, i) => Math.abs(x.exposure_index - c.table[i].exposure_index) < 0.0101
                      && Math.abs(x.protein_kg - c.table[i].protein_kg) < 0.11);
  if (!same && bad++ < 3) console.log(JSON.stringify({case: c.s, got: {r, pick, why}, want: c.level, pick2: c.pick}));
}
console.log(cases.length, "cases", bad, "bad");
process.exit(bad ? 1 : 0);
"""


def cases(inp) -> list[dict]:
    out = []
    grid = itertools.product(A.PRODUCTS, (None, 1, 2, 3), ("none", "negative", "detected"), (False, True),
                             (False, True), (0.0, 2.0, 6.0), ((0, 0), (5, 1), (40, 11), (20, 0), (10, 12)),
                             (None, "0.5", "2.0", "<10", "abc"))
    for product, cat, result, line, spec, hours, (n, k), cfu in grid:
        if cfu and product != "Raw breaded stuffed chicken":
            continue
        s = A.Situation("MO", 7, product, 2500, fsis_category=cat, lot_result=result, has_cooked_line=line,
                        customer_limit=spec, hours_above_40f=hours, plant_samples=n, plant_positives=k,
                        cfu_per_g=cfu)
        level, pct, why = A.risk_level(s, inp)
        pick, reason = A.recommend(s, inp)
        c = A.plant_self_check(s)
        out.append({"s": s.__dict__, "level": level, "pct": pct, "why": why, "pick": pick, "reason": reason,
                    "message": c.message if c else None, "note": c.published_note if c else None,
                    "table": A.compare_actions(s, inp).to_dict("records")})
    return out


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_web_engine_matches_python(tmp_path):
    inp = A.load_inputs()
    (tmp_path / "golden.json").write_text(json.dumps({"data": export_web.build(), "cases": cases(inp)}, default=bool))
    script = tmp_path / "check.mjs"
    script.write_text(CHECK % (ROOT / "web" / "engine.js").resolve().as_uri())
    r = subprocess.run(["node", str(script), str(tmp_path / "golden.json")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
