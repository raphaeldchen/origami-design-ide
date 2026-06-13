import multiprocessing as mp, json
QUAD=[{"id":0,"parent_id":None,"length":0},{"id":1,"parent_id":0,"length":0.4},
      {"id":2,"parent_id":1,"length":0.4},{"id":3,"parent_id":0,"length":0.5},
      {"id":4,"parent_id":1,"length":0.5},{"id":5,"parent_id":2,"length":0.5}]
def w(q):
    import headless_treemaker as ht
    e=ht.HeadlessTreemaker(); e.init_paper(1.0,1.0)
    e.build_tree_from_json(json.dumps(QUAD)); e.run_scale_optimization()
    q.put(e.debug_crease_report())
def main():
    ctx=mp.get_context("spawn"); q=ctx.Queue()
    p=ctx.Process(target=w,args=(q,)); p.start(); p.join(40)
    print(q.get())
if __name__=="__main__": main()
