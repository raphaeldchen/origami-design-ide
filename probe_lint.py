"""Compile structured trees via BOTH paths (scale-only and strain) and run each
successful FOLD through the Oriedita flat-foldability linter. Goal: find a tree
that compiles AND passes flat-foldability (the full happy path)."""
from __future__ import annotations
import json, multiprocessing as mp
import linter_server


def _worker(q, nodes_json, pairs, strain):
    try:
        import headless_treemaker as ht
        e = ht.HeadlessTreemaker(); e.init_paper(1.0, 1.0)
        e.build_tree_from_json(nodes_json)
        for a, b in pairs:
            e.apply_symmetry(int(a), int(b))
        e.run_scale_optimization()
        fold = (e.run_strain_optimization_and_export() if strain
                else e.build_and_export())
        q.put(("ok", fold))
    except BaseException as exc:  # noqa
        q.put(("err", repr(exc)[:100]))


def compile_tree(nodes, pairs, strain):
    ctx = mp.get_context("spawn"); q = ctx.Queue()
    p = ctx.Process(target=_worker, args=(q, json.dumps(nodes), pairs, strain))
    p.start(); p.join(40)
    if p.is_alive():
        p.terminate(); p.join(); return ("timeout", "")
    return q.get() if not q.empty() else ("crash", f"exit {p.exitcode}")


def N(i, par, ln):
    return {"id": i, "parent_id": par, "length": ln}


CASES = [
    ("spine-2branch quad",
     [N(0, None, 0), N(1, 0, 0.4), N(2, 1, 0.4),
      N(3, 0, 0.5), N(4, 1, 0.5), N(5, 2, 0.5)], []),
    ("4-flap H-shape",
     [N(0, None, 0), N(1, 0, 0.4),
      N(2, 0, 0.5), N(3, 0, 0.5), N(4, 1, 0.5), N(5, 1, 0.5)], [[2, 3], [4, 5]]),
    ("5-leaf caterpillar",
     [N(0, None, 0), N(1, 0, 0.25), N(2, 1, 0.25), N(3, 2, 0.25),
      N(4, 0, 0.5), N(5, 1, 0.5), N(6, 2, 0.5), N(7, 3, 0.5)], []),
]


def lint_summary(fold):
    res = linter_server.validate_flat_foldability(fold)
    first = res.splitlines()[0]
    return ("PASS-LINT" if res.strip().startswith(("Flat-foldable", "PASS",
            "OK", "Valid")) and "FAILED" not in first else "FAIL-LINT"), first


def main():
    for name, nodes, pairs in CASES:
        for strain in (False, True):
            tag = "strain" if strain else "scale "
            st, payload = compile_tree(nodes, pairs, strain)
            if st != "ok":
                print(f"{name:22s} [{tag}] COMPILE-{st}: {payload[:70]}")
                continue
            d = json.loads(payload)
            lr, first = lint_summary(payload)
            print(f"{name:22s} [{tag}] compiled V={len(d['vertices_coords'])} "
                  f"E={len(d['edges_vertices'])} -> {lr}: {first[:60]}")


if __name__ == "__main__":
    main()
