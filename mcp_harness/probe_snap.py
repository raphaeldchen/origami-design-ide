import json, multiprocessing as mp
import linter_server
STAR=[{"id":0,"parent_id":None,"length":0},{"id":1,"parent_id":0,"length":1.0},
      {"id":2,"parent_id":0,"length":1.0},{"id":3,"parent_id":0,"length":1.0},{"id":4,"parent_id":0,"length":1.0}]
def w(q):
    import headless_treemaker as ht
    e=ht.HeadlessTreemaker(); e.init_paper(1.0,1.0)
    e.build_tree_from_json(json.dumps(STAR)); e.run_scale_optimization()
    q.put(e.build_and_export())
def first(r): return r.splitlines()[0]
def main():
    ctx=mp.get_context("spawn"); q=ctx.Queue()
    p=ctx.Process(target=w,args=(q,)); p.start(); p.join(40)
    f=json.loads(q.get())
    print("star as-is        :", first(linter_server.validate_flat_foldability(json.dumps(f))))
    for ndp in (4,3,2):
        g=dict(f); g["vertices_coords"]=[[round(x,ndp),round(y,ndp)] for x,y in f["vertices_coords"]]
        print(f"star snapped {ndp}dp   :", first(linter_server.validate_flat_foldability(json.dumps(g))))
if __name__=="__main__": main()
