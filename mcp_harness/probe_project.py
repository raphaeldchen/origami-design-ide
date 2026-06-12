"""Verify the active-path projection: residual before/after + end-to-end lint."""
import json, multiprocessing as mp
import linter_server

def N(i, p, l): return {"id": i, "parent_id": p, "length": l}

CASES = {
 "4-flap star":        ([N(0,None,0),N(1,0,1.0),N(2,0,1.0),N(3,0,1.0),N(4,0,1.0)], []),
 "4-flap H-shape":     ([N(0,None,0),N(1,0,0.4),N(2,0,0.5),N(3,0,0.5),N(4,1,0.5),N(5,1,0.5)], [[2,3],[4,5]]),
 "spine-2branch quad": ([N(0,None,0),N(1,0,0.4),N(2,1,0.4),N(3,0,0.5),N(4,1,0.5),N(5,2,0.5)], []),
}

def w(q, nodes, pairs):
    import headless_treemaker as ht
    e = ht.HeadlessTreemaker(); e.init_paper(1.0, 1.0)
    e.build_tree_from_json(json.dumps(nodes))
    for a, b in pairs: e.apply_symmetry(a, b)
    e.run_scale_optimization()
    report = e.debug_active_path_report()        # before -> after residual
    # Fresh session for the full build (debug report mutated coords already, but
    # build_and_export re-projects deterministically; keep them independent).
    e2 = ht.HeadlessTreemaker(); e2.init_paper(1.0, 1.0)
    e2.build_tree_from_json(json.dumps(nodes))
    for a, b in pairs: e2.apply_symmetry(a, b)
    e2.run_scale_optimization()
    q.put((report, e2.build_and_export()))

def main():
    for name, (nodes, pairs) in CASES.items():
        ctx = mp.get_context("spawn"); q = ctx.Queue()
        p = ctx.Process(target=w, args=(q, nodes, pairs)); p.start(); p.join(40)
        if p.is_alive(): p.terminate(); print(f"{name:22s} TIMEOUT"); continue
        if q.empty(): print(f"{name:22s} CRASH exit={p.exitcode}"); continue
        report, fold = q.get()
        d = json.loads(fold)
        verdict = linter_server.validate_flat_foldability(fold).splitlines()[0]
        print(f"{name:22s} {report.strip()}")
        print(f"{'':22s} V={len(d['vertices_coords'])} E={len(d['edges_vertices'])} -> {verdict}")

if __name__ == "__main__":
    main()
