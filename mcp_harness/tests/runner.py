"""Compile/lint a Metric Tree in an isolated spawned subprocess so an engine
SIGSEGV or infinite loop becomes a catchable verdict, never a harness crash.

Import contract (set by the Makefile): both `mcp_harness/` and
`mcp_harness/tests/` are on sys.path, so the engine (`headless_treemaker`,
`linter_server`) and this module import in the spawned child (spawn propagates
sys.path). Run via:  PYTHONPATH=.:tests python -m pytest tests/   from mcp_harness/.
"""
from __future__ import annotations
import json
import multiprocessing as mp

# Geometry keys we compare; metadata (file_*/frame_*) is intentionally ignored.
GEOM_KEYS = ("vertices_coords", "edges_vertices", "edges_assignment")


def _worker(q, nodes_json, pairs):
    try:
        import headless_treemaker as ht
        e = ht.HeadlessTreemaker(); e.init_paper(1.0, 1.0)
        e.build_tree_from_json(nodes_json)
        for a, b in pairs:
            e.apply_symmetry(int(a), int(b))
        e.run_scale_optimization()
        q.put(("ok", e.build_and_export()))
    except BaseException as exc:  # noqa: BLE001
        q.put(("err", repr(exc)[:120]))


def compile_tree(nodes, pairs, timeout=40):
    """Return ("ok", fold_json_str) | ("err", msg) | ("CRASH", info) | ("HANG", "")."""
    ctx = mp.get_context("spawn"); q = ctx.Queue()
    p = ctx.Process(target=_worker, args=(q, json.dumps(nodes), pairs))
    p.start(); p.join(timeout)
    if p.is_alive():
        p.terminate(); p.join(); return ("HANG", "")
    if q.empty():
        return ("CRASH", f"exit {p.exitcode}")
    return q.get()


def lint(fold_json_str):
    """First line of the Oriedita verdict for a FOLD JSON string."""
    import linter_server
    return linter_server.validate_flat_foldability(fold_json_str).splitlines()[0].strip()


def verdict_for(nodes, pairs, timeout=40):
    """The regression verdict for a case: PASS | FAIL-LINT | CLEAN-ERR | CRASH | HANG."""
    st, payload = compile_tree(nodes, pairs, timeout=timeout)
    if st == "ok":
        return "PASS" if lint(payload) == "Pass" else "FAIL-LINT"
    if st == "err":
        return "CLEAN-ERR"
    return st  # CRASH or HANG


def fold_geom(fold):
    """Extract only the comparable geometry keys from a parsed FOLD dict."""
    return {k: fold[k] for k in GEOM_KEYS if k in fold}
