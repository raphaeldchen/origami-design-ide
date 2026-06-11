"""Decisive: are v5/v9 failures GEOMETRY (precision) or LABEL (F-mislabel)?
Take the quad FOLD and try reassigning the F creases incident to interior
vertices to folds. If any reassignment clears Oriedita -> it's a CalcFold
labeling bug, NOT optimizer precision."""
import json, itertools, multiprocessing as mp
import linter_server

QUAD=[{"id":0,"parent_id":None,"length":0},{"id":1,"parent_id":0,"length":0.4},
      {"id":2,"parent_id":1,"length":0.4},{"id":3,"parent_id":0,"length":0.5},
      {"id":4,"parent_id":1,"length":0.5},{"id":5,"parent_id":2,"length":0.5}]
INTERIOR={4,5,9}
def build(q):
    import headless_treemaker as ht
    e=ht.HeadlessTreemaker(); e.init_paper(1.0,1.0)
    e.build_tree_from_json(json.dumps(QUAD)); e.run_scale_optimization()
    q.put(e.build_and_export())
def vcount(r): return r.splitlines()[0]
def main():
    ctx=mp.get_context("spawn"); q=ctx.Queue()
    p=ctx.Process(target=build,args=(q,)); p.start(); p.join(40)
    f=json.loads(q.get()); E=f["edges_vertices"]; A=f["edges_assignment"]
    # F edges touching an interior vertex
    fidx=[i for i,((a,b),asg) in enumerate(zip(E,A)) if asg=="F" and (a in INTERIOR or b in INTERIOR)]
    print(f"F edges touching interior vertices: {[(i,E[i]) for i in fidx]}")
    print("baseline:", vcount(linter_server.validate_flat_foldability(json.dumps(f))))
    # try each combination of M/V for those F edges
    for combo in itertools.product("MV", repeat=len(fidx)):
        g=dict(f); a2=list(A)
        for i,c in zip(fidx,combo): a2[i]=c
        g["edges_assignment"]=a2
        print(f"  {dict(zip(fidx,combo))}: {vcount(linter_server.validate_flat_foldability(json.dumps(g)))}")
if __name__=="__main__": main()
