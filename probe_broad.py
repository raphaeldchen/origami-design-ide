"""Broad sweep (GUI-style scale-only build) to find any tree that fully compiles
to a FOLD now that the molecule crease/facet network is built. Each trial runs
in a spawned child so a crash fails only that trial."""
from __future__ import annotations
import json, multiprocessing as mp


def _worker(q, nodes_json, pairs, w, h):
    try:
        import headless_treemaker as ht
        e = ht.HeadlessTreemaker()
        e.init_paper(w, h)
        e.build_tree_from_json(nodes_json)
        for a, b in pairs:
            e.apply_symmetry(int(a), int(b))
        s = e.run_scale_optimization()
        q.put(("ok", s, e.build_and_export()))
    except BaseException as exc:  # noqa
        q.put(("err", repr(exc)[:140], ""))


def run(nodes, pairs, w=1.0, h=1.0):
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    p = ctx.Process(target=_worker, args=(q, json.dumps(nodes), pairs, w, h))
    p.start(); p.join(60)
    if p.is_alive():
        p.terminate(); p.join(); return ("timeout", "", "")
    if not q.empty():
        return q.get()
    return ("crash", f"exit {p.exitcode}", "")


def N(i, parent, length, **kw):
    d = {"id": i, "parent_id": parent, "length": length}; d.update(kw); return d


CASES = [
    # Structured / caterpillar trees: leaves hang off DISTINCT branch nodes
    # along a spine, giving normal multi-polygon molecules (not a single hub).
    ("spine-2branch quad (legs off 2 spine nodes)",
     [N(0, None, 0), N(1, 0, 0.4), N(2, 1, 0.4),        # spine 0-1-2
      N(3, 0, 0.5), N(4, 1, 0.5), N(5, 2, 0.5)], []),   # 3 legs off distinct nodes
    ("spine-3branch, 4 legs",
     [N(0, None, 0), N(1, 0, 0.3), N(2, 1, 0.3),
      N(3, 0, 0.5), N(4, 1, 0.5), N(5, 2, 0.5), N(6, 2, 0.5)], []),
    ("simple 3-flap off a stem (root-stem then 3 leaves)",
     [N(0, None, 0), N(1, 0, 0.3),
      N(2, 1, 0.5), N(3, 1, 0.5), N(4, 1, 0.5)], []),
    ("4-flap from 2 branch nodes (H-shape)",
     [N(0, None, 0), N(1, 0, 0.4),
      N(2, 0, 0.5), N(3, 0, 0.5), N(4, 1, 0.5), N(5, 1, 0.5)],
     [[2, 3], [4, 5]]),
    ("asymmetric 3-flap star (unequal legs)",
     [N(0, None, 0), N(1, 0, 0.9), N(2, 0, 0.6), N(3, 0, 0.4)], []),
    ("classic 4-flap star (control)",
     [N(0, None, 0), N(1, 0, 1.0), N(2, 0, 1.0), N(3, 0, 1.0), N(4, 0, 1.0)], []),
]


def main():
    anypass = False
    for name, nodes, pairs in CASES:
        st, a, fold = run(nodes, pairs)
        if st == "ok":
            d = json.loads(fold)
            print(f"PASS  {name}\n      scale={a:.5f} V={len(d['vertices_coords'])} "
                  f"E={len(d['edges_vertices'])} assign={set(d.get('edges_assignment', []))}")
            anypass = True
            with open("/tmp/first_fold.fold", "w") as fh:
                fh.write(fold)
        else:
            print(f"FAIL  {name}\n      [{st}] {a}")
    print("\n=> at least one full FOLD built!" if anypass
          else "\n=> none fully compiled")


if __name__ == "__main__":
    main()
