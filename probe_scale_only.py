"""Probe the GUI-style path: scale-opt -> build_and_export (NO strain opt).

Mirrors TreeMaker's Action->Build Crease Pattern, which never runs strain
optimization. Each trial runs in a spawned child so a facet-builder SIGSEGV
fails that trial, not the sweep.
"""

from __future__ import annotations

import json
import multiprocessing as mp


def _worker(queue, nodes_json, pairs, w, h):
    try:
        import headless_treemaker as ht
        eng = ht.HeadlessTreemaker()
        eng.init_paper(w, h)
        eng.build_tree_from_json(nodes_json)
        for a, b in pairs:
            eng.apply_symmetry(int(a), int(b))
        scale = eng.run_scale_optimization()
        fold = eng.build_and_export()          # <-- scale-only, GUI-style
        queue.put(("ok", scale, fold))
    except BaseException as exc:               # noqa: BLE001
        queue.put(("err", repr(exc), ""))


def run(nodes, pairs, w=1.0, h=1.0):
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    p = ctx.Process(target=_worker, args=(q, json.dumps(nodes), pairs, w, h))
    p.start()
    p.join(60)
    if p.is_alive():
        p.terminate(); p.join()
        return ("timeout", "", "")
    if p.exitcode != 0:
        return ("crash", f"exit {p.exitcode}", "")
    return q.get() if not q.empty() else ("crash", f"exit {p.exitcode}", "")


CANDIDATES = [
    ("4-flap star (2 sym pairs)",
     [{"id": 0, "parent_id": None, "length": 0},
      {"id": 1, "parent_id": 0, "length": 1.0},
      {"id": 2, "parent_id": 0, "length": 1.0},
      {"id": 3, "parent_id": 0, "length": 1.0},
      {"id": 4, "parent_id": 0, "length": 1.0}],
     [[1, 2], [3, 4]]),
    ("4-flap star, no symmetry",
     [{"id": 0, "parent_id": None, "length": 0},
      {"id": 1, "parent_id": 0, "length": 1.0},
      {"id": 2, "parent_id": 0, "length": 1.0},
      {"id": 3, "parent_id": 0, "length": 1.0},
      {"id": 4, "parent_id": 0, "length": 1.0}],
     []),
    ("3-flap star",
     [{"id": 0, "parent_id": None, "length": 0},
      {"id": 1, "parent_id": 0, "length": 1.0},
      {"id": 2, "parent_id": 0, "length": 1.0},
      {"id": 3, "parent_id": 0, "length": 1.0}],
     []),
]


def main():
    for name, nodes, pairs in CANDIDATES:
        status, a, fold = run(nodes, pairs)
        if status == "ok":
            d = json.loads(fold)
            print(f"PASS  {name}  scale={a:.6f}  "
                  f"V={len(d.get('vertices_coords', []))} "
                  f"E={len(d.get('edges_vertices', []))}")
        else:
            print(f"FAIL  {name}  [{status}] {str(a)[:120]}")


if __name__ == "__main__":
    main()
