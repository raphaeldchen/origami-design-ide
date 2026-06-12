"""Broad robustness sweep: compile a variety of metric trees (varying node count,
depth, edge weights, symmetry) via the scale-only path, catch crash/hang/clean-
error per-case with spawn+timeout, and lint each successful FOLD. Catalogs the
engine's behavior envelope and seeds the future Tier-2.5 heuristic checker.

Run: .venv/bin/python probe_sweep.py
"""
from __future__ import annotations
import json, multiprocessing as mp
import linter_server


def _worker(q, nodes_json, pairs):
    try:
        import headless_treemaker as ht
        e = ht.HeadlessTreemaker(); e.init_paper(1.0, 1.0)
        e.build_tree_from_json(nodes_json)
        for a, b in pairs:
            e.apply_symmetry(int(a), int(b))
        e.run_scale_optimization()
        q.put(("ok", e.build_and_export()))
    except BaseException as exc:  # noqa
        q.put(("err", repr(exc)[:90]))


def run(nodes, pairs, timeout=40):
    ctx = mp.get_context("spawn"); q = ctx.Queue()
    p = ctx.Process(target=_worker, args=(q, json.dumps(nodes), pairs))
    p.start(); p.join(timeout)
    if p.is_alive():
        p.terminate(); p.join(); return ("HANG", "")
    if q.empty():
        return ("CRASH", f"exit {p.exitcode}")
    return q.get()


def N(i, par, ln):
    return {"id": i, "parent_id": par, "length": ln}


def lint(fold):
    return linter_server.validate_flat_foldability(fold).splitlines()[0]


# ---- catalog of trees --------------------------------------------------------
def star(k, ln=1.0):
    return [N(0, None, 0)] + [N(i, 0, ln) for i in range(1, k + 1)], []


def caterpillar(spine, leaf_len=0.5, spine_len=0.25):
    """spine nodes 1..spine off a chain from root 0, a leaf hanging off each
    spine node (incl root)."""
    nodes = [N(0, None, 0)]
    for i in range(1, spine + 1):
        nodes.append(N(i, i - 1, spine_len))
    nxt = spine + 1
    for s in range(0, spine + 1):
        nodes.append(N(nxt, s, leaf_len)); nxt += 1
    return nodes, []


def symmetric_pairs_star(k, ln=1.0):
    nodes, _ = star(k, ln)
    pairs = [[i, i + 1] for i in range(1, k, 2)]
    return nodes, pairs


CASES = [
    ("star-3",            star(3)),
    ("star-4",            star(4)),
    ("star-5",            star(5)),
    ("star-6",            star(6)),
    ("star-8",            star(8)),
    ("star-4-sym",        symmetric_pairs_star(4)),
    ("star-6-sym",        symmetric_pairs_star(6)),
    ("cat-spine2",        caterpillar(2)),
    ("cat-spine3",        caterpillar(3)),   # the original 5-leaf caterpillar shape
    ("cat-spine4",        caterpillar(4)),
    ("cat-spine5",        caterpillar(5)),
    ("cat-long-legs",     caterpillar(3, leaf_len=0.8, spine_len=0.15)),
    ("cat-short-legs",    caterpillar(3, leaf_len=0.3, spine_len=0.3)),
    ("uneven-star",       ([N(0, None, 0), N(1, 0, 1.0), N(2, 0, 0.6),
                            N(3, 0, 0.4), N(4, 0, 0.8)], [])),
    ("deep-chain",        ([N(0, None, 0), N(1, 0, 0.3), N(2, 1, 0.3),
                            N(3, 2, 0.3), N(4, 3, 0.3), N(5, 4, 0.5),
                            N(6, 0, 0.5)], [])),
    ("two-level-tree",    ([N(0, None, 0), N(1, 0, 0.3), N(2, 0, 0.3),
                            N(3, 1, 0.5), N(4, 1, 0.5), N(5, 2, 0.5),
                            N(6, 2, 0.5)], [])),
]


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
