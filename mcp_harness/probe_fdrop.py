"""With tight geometry: does dropping F (unfolded-hinge) edges make the quad pass?
Tests three handlings: as-is, drop-F, drop-F+merge-collinear-into-passthrough."""
import json, math, multiprocessing as mp
import linter_server
QUAD=[{"id":0,"parent_id":None,"length":0},{"id":1,"parent_id":0,"length":0.4},
      {"id":2,"parent_id":1,"length":0.4},{"id":3,"parent_id":0,"length":0.5},
      {"id":4,"parent_id":1,"length":0.5},{"id":5,"parent_id":2,"length":0.5}]
def w(q):
    import headless_treemaker as ht
    e=ht.HeadlessTreemaker(); e.init_paper(1.0,1.0)
    e.build_tree_from_json(json.dumps(QUAD)); e.run_scale_optimization()
    q.put(e.build_and_export())
def first(r): return r.splitlines()[0]
def main():
    ctx=mp.get_context("spawn"); q=ctx.Queue()
    p=ctx.Process(target=w,args=(q,)); p.start(); p.join(40)
    f=json.loads(q.get()); E=f["edges_vertices"]; A=f["edges_assignment"]
    print("as-is   :", first(linter_server.validate_flat_foldability(json.dumps(f))))
    keep=[i for i,a in enumerate(A) if a!="F"]
    g=dict(f); g["edges_vertices"]=[E[i] for i in keep]; g["edges_assignment"]=[A[i] for i in keep]
    if "edges_foldAngle" in f: g["edges_foldAngle"]=[f["edges_foldAngle"][i] for i in keep]
    print("drop-F  :", first(linter_server.validate_flat_foldability(json.dumps(g))))
if __name__=="__main__": main()
