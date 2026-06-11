import multiprocessing as mp, json
def N(i,p,l): return {"id":i,"parent_id":p,"length":l}
H=[N(0,None,0),N(1,0,0.4),N(2,0,0.5),N(3,0,0.5),N(4,1,0.5),N(5,1,0.5)]
PAIRS=[[2,3],[4,5]]
def w(q):
    import headless_treemaker as ht
    e=ht.HeadlessTreemaker(); e.init_paper(1.0,1.0)
    e.build_tree_from_json(json.dumps(H))
    for a,b in PAIRS: e.apply_symmetry(a,b)
    e.run_scale_optimization(); q.put(e.debug_crease_report())
def main():
    ctx=mp.get_context("spawn"); q=ctx.Queue()
    p=ctx.Process(target=w,args=(q,)); p.start(); p.join(40)
    rep=q.get()
    print(rep)
    nu=sum(1 for ln in rep.splitlines() if "uHINGE" in ln)
    print(f"\n# uHINGE creases in H-shape: {nu}")
if __name__=="__main__": main()
