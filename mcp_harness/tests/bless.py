"""Regenerate the regression baselines from CURRENT engine output.

Run deliberately when the engine legitimately changes; review the resulting
diff to baseline_verdicts.json and goldens/ as the record of what changed.

  cd mcp_harness && PYTHONPATH=.:tests .venv/bin/python tests/bless.py
"""
from __future__ import annotations
import json
import os

import cases
import runner

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE = os.path.join(HERE, "baseline_verdicts.json")
GOLDEN_DIR = os.path.join(HERE, "goldens")


def bless_verdicts():
    verdicts = {}
    for name, (nodes, pairs) in cases.CASES:
        v = runner.verdict_for(nodes, pairs)
        verdicts[name] = v
        print(f"{name:18s} {v}")
    with open(BASELINE, "w") as f:
        json.dump(verdicts, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"\nwrote {BASELINE}")


def bless_goldens():
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    for name in cases.GOLDEN_CASE_NAMES:
        nodes, pairs = cases.CASES_BY_NAME[name]
        st, payload = runner.compile_tree(nodes, pairs)
        assert st == "ok", f"golden case {name} did not compile: {st} {payload}"
        fold = json.loads(payload)
        path = os.path.join(GOLDEN_DIR, f"{name}.fold")
        with open(path, "w") as f:
            json.dump(runner.fold_geom(fold), f, indent=2, sort_keys=True)
            f.write("\n")
        print(f"wrote {path}")


if __name__ == "__main__":
    bless_verdicts()
    bless_goldens()
