"""Broad robustness sweep: compile a variety of metric trees (varying node count,
depth, edge weights, symmetry) via the scale-only path, catch crash/hang/clean-
error per-case with spawn+timeout, and lint each successful FOLD. Catalogs the
engine's behavior envelope and seeds the future Tier-2.5 heuristic checker.

Run: .venv/bin/python probe_sweep.py
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tests"))
import json
from cases import CASES  # canonical catalog (shared with the regression suite)
from runner import compile_tree as run, lint  # shared spawn-isolation + lint


def main():
    print(f"{'case':18s} {'V':>4} {'E':>4}  status / verdict")
    print("-" * 64)
    tally = {}
    for name, (nodes, pairs) in CASES:
        st, payload = run(nodes, pairs)
        if st == "ok":
            d = json.loads(payload); v = lint(payload)
            cat = "PASS" if v.strip() == "Pass" else "FAIL-LINT"
            print(f"{name:18s} {len(d['vertices_coords']):>4} "
                  f"{len(d['edges_vertices']):>4}  {cat}: {v[:34]}")
        elif st == "err":
            cat = "CLEAN-ERR"
            print(f"{name:18s} {'-':>4} {'-':>4}  CLEAN-ERR: {payload[:40]}")
        else:
            cat = st
            print(f"{name:18s} {'-':>4} {'-':>4}  **{st}** {payload}")
        tally[cat] = tally.get(cat, 0) + 1
    print("-" * 64)
    print("tally:", dict(sorted(tally.items())))


if __name__ == "__main__":
    main()
