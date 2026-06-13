"""Clean end-to-end verification: compile (scale-only) + raw Oriedita verdict."""
import json, multiprocessing as mp
import linter_server
def N(i,p,l): return {"id":i,"parent_id":p,"length":l}
CASES={
 "4-flap star":        ([N(0,None,0),N(1,0,1.0),N(2,0,1.0),N(3,0,1.0),N(4,0,1.0)],[]),
 "4-flap H-shape":     ([N(0,None,0),N(1,0,0.4),N(2,0,0.5),N(3,0,0.5),N(4,1,0.5),N(5,1,0.5)],[[2,3],[4,5]]),
 "spine-2branch quad": ([N(0,None,0),N(1,0,0.4),N(2,1,0.4),N(3,0,0.5),N(4,1,0.5),N(5,2,0.5)],[]),
}
def w(q,nodes,pairs):
    import headless_treemaker as ht
    e=ht.HeadlessTreemaker(); e.init_paper(1.0,1.0)
    e.build_tree_from_json(json.dumps(nodes))
    for a,b in pairs: e.apply_symmetry(a,b)
    e.run_scale_optimization(); q.put(e.build_and_export())
def main():
    for name,(nodes,pairs) in CASES.items():
        ctx=mp.get_context("spawn"); q=ctx.Queue()
        p=ctx.Process(target=w,args=(q,nodes,pairs)); p.start(); p.join(40)
        if p.is_alive(): p.terminate(); print(f"{name:22s} TIMEOUT"); continue
        if q.empty(): print(f"{name:22s} CRASH exit={p.exitcode}"); continue
        fold=q.get(); d=json.loads(fold)
        verdict=linter_server.validate_flat_foldability(fold).splitlines()[0]
        print(f"{name:22s} V={len(d['vertices_coords'])} E={len(d['edges_vertices'])} -> {verdict}")
if __name__=="__main__": main()
