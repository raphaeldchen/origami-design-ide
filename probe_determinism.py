"""Is the star result deterministic? Run the same build N times."""
import json, multiprocessing as mp
import linter_server
STAR=[{"id":0,"parent_id":None,"length":0},{"id":1,"parent_id":0,"length":1.0},
      {"id":2,"parent_id":0,"length":1.0},{"id":3,"parent_id":0,"length":1.0},{"id":4,"parent_id":0,"length":1.0}]
def w(q):
    import headless_treemaker as ht
    e=ht.HeadlessTreemaker(); e.init_paper(1.0,1.0)
    e.build_tree_from_json(json.dumps(STAR)); e.run_scale_optimization()
    q.put(e.build_and_export())
def main():
    for i in range(6):
        ctx=mp.get_context("spawn"); q=ctx.Queue()
        p=ctx.Process(target=w,args=(q,)); p.start(); p.join(40)
        d=json.loads(q.get())
        v=linter_server.validate_flat_foldability(json.dumps(d)).splitlines()[0]
        # first leaf coords as a fingerprint of which optimum
        fp=tuple(round(c,4) for c in d["vertices_coords"][1])
        print(f"run {i}: V={len(d['vertices_coords'])} leaf1={fp} -> {v[:50]}")
if __name__=="__main__": main()
