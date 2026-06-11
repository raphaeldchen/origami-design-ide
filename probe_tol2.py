"""Narrow the threshold: does tightening to ~1e-7..1e-12 residual pass?
Determines fix: tighter ALM (if tol ~1e-6) vs exact snap (if tol ~0)."""
import json, math
import linter_server
import probe_tol as pt
def first(r): return r.splitlines()[0]
print(f"{'delta(deg)':>12} {'resid(deg)':>16}  result")
for delta in (5e-1,1e-1,1e-2,1e-3,1e-4,1e-5,1e-6,1e-7,1e-8,1e-9,1e-10,1e-11):
    f, resid = pt.make_fold(delta)
    res = first(linter_server.validate_flat_foldability(json.dumps(f)))
    v = "PASS" if res.startswith("Pass") else "FAIL"
    print(f"{delta:12.3g} {resid:16.3e}  {v}")
