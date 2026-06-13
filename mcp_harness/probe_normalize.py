"""Prove the v9 fix: a foldability-preserving FOLD normalization.

Two transforms, each provably neutral for flat-foldability:
  (1) drop flat (F / UNFOLDED) creases  -- impose no fold constraint; Oriedita
      already imports F as an auxiliary (non-fold) line.
  (2) merge a degree-2 vertex whose two incident creases are COLLINEAR and the
      SAME assignment -- such a vertex is just a midpoint of one straight fold
      line; deleting it and joining the two far endpoints changes no angle and
      no layer order.

spine-2branch quad v9 is exactly case (2): two collinear valleys meeting at a
spurious deg-2 vertex (its only other creases are flat hinges, removed by (1)).
Oriedita rejects it only because it does not auto-merge such vertices.

Expected: star & H-shape stay Pass (normalization is neutral); quad drops from
2 violations -> 1 (v9 gone; v5 precision residual remains, a separate issue).
"""
import json, math, multiprocessing as mp
import linter_server

N = lambda i, p, l: {"id": i, "parent_id": p, "length": l}
CASES = {
    "4-flap star":        ([N(0,None,0),N(1,0,1.0),N(2,0,1.0),N(3,0,1.0),N(4,0,1.0)], []),
    "4-flap H-shape":     ([N(0,None,0),N(1,0,0.4),N(2,0,0.5),N(3,0,0.5),N(4,1,0.5),N(5,1,0.5)], [[2,3],[4,5]]),
    "spine-2branch quad": ([N(0,None,0),N(1,0,0.4),N(2,1,0.4),N(3,0,0.5),N(4,1,0.5),N(5,2,0.5)], []),
}
COLLINEAR_TOL = 1e-3   # degrees; the engine's collinear creases sit at < 1e-3 dev


def _angle(V, a, b):
    (x0, y0), (x1, y1) = V[a], V[b]
    return math.degrees(math.atan2(y1 - y0, x1 - x0)) % 360


def normalize_clean(fold):
    f = json.loads(fold) if isinstance(fold, str) else dict(fold)
    V = [list(p) for p in f["vertices_coords"]]
    edges = [[list(e), a] for e, a in
             zip(f["edges_vertices"], f["edges_assignment"]) if a != "F"]

    changed = True
    while changed:
        changed = False
        inc = {}
        for ei, (e, a) in enumerate(edges):
            inc.setdefault(e[0], []).append(ei)
            inc.setdefault(e[1], []).append(ei)
        for v, eids in inc.items():
            if len(eids) != 2:
                continue
            i1, i2 = eids
            (e1, a1), (e2, a2) = edges[i1], edges[i2]
            if a1 != a2:
                continue
            n1 = e1[1] if e1[0] == v else e1[0]
            n2 = e2[1] if e2[0] == v else e2[0]
            if n1 == n2:
                continue
            dev = abs((_angle(V, v, n1) - _angle(V, v, n2)) % 360 - 180)
            if dev > COLLINEAR_TOL:
                continue
            edges[i1] = [[n1, n2], a1]
            del edges[i2]
            changed = True
            break

    # re-index to drop now-unused vertices
    used = sorted({x for e, _ in edges for x in e})
    remap = {old: new for new, old in enumerate(used)}
    g = dict(f)
    g["vertices_coords"] = [V[i] for i in used]
    g["edges_vertices"] = [[remap[e[0]], remap[e[1]]] for e, _ in edges]
    g["edges_assignment"] = [a for _, a in edges]
    g.pop("edges_foldAngle", None)
    return json.dumps(g)


def w(q, nodes, pairs):
    import headless_treemaker as ht
    e = ht.HeadlessTreemaker(); e.init_paper(1.0, 1.0)
    e.build_tree_from_json(json.dumps(nodes))
    for a, b in pairs:
        e.apply_symmetry(a, b)
    e.run_scale_optimization(); q.put(e.build_and_export())


def first(r): return r.splitlines()[0]


def main():
    for name, (nodes, pairs) in CASES.items():
        ctx = mp.get_context("spawn"); q = ctx.Queue()
        p = ctx.Process(target=w, args=(q, nodes, pairs)); p.start(); p.join(40)
        if q.empty():
            print(f"{name:22s} CRASH/timeout exit={p.exitcode}"); continue
        fold = q.get()
        raw = first(linter_server.validate_flat_foldability(fold))
        norm = normalize_clean(fold)
        d0 = json.loads(fold); d1 = json.loads(norm)
        normv = first(linter_server.validate_flat_foldability(norm))
        print(f"{name:22s} raw[V{len(d0['vertices_coords'])} E{len(d0['edges_vertices'])}]: {raw}")
        print(f"{'':22s} norm[V{len(d1['vertices_coords'])} E{len(d1['edges_vertices'])}]: {normv}")


if __name__ == "__main__":
    main()
