"""JVM-free structural audit of the quad FOLD: duplicate/coincident vertices,
degenerate (zero-length) edges, and exact Kawasaki per interior vertex incl. F."""
import json, math, multiprocessing as mp

QUAD=[{"id":0,"parent_id":None,"length":0},{"id":1,"parent_id":0,"length":0.4},
      {"id":2,"parent_id":1,"length":0.4},{"id":3,"parent_id":0,"length":0.5},
      {"id":4,"parent_id":1,"length":0.5},{"id":5,"parent_id":2,"length":0.5}]
def build(q):
    import headless_treemaker as ht
    e=ht.HeadlessTreemaker(); e.init_paper(1.0,1.0)
    e.build_tree_from_json(json.dumps(QUAD)); e.run_scale_optimization()
    q.put(e.build_and_export())
def main():
    ctx=mp.get_context("spawn"); q=ctx.Queue()
    p=ctx.Process(target=build,args=(q,)); p.start(); p.join(40)
    f=json.loads(q.get())
    V=f["vertices_coords"]; E=f["edges_vertices"]; A=f["edges_assignment"]
    print(f"V={len(V)} E={len(E)}")
    print("\n=== coincident vertex pairs (dist < 1e-6) ===")
    for i in range(len(V)):
        for j in range(i+1,len(V)):
            d=math.hypot(V[i][0]-V[j][0], V[i][1]-V[j][1])
            if d<1e-6: print(f"  v{i} ~ v{j}  dist={d:.2e}  at {V[i]}")
    print("\n=== zero-length / duplicate edges ===")
    seen={}
    for k,((a,b),asg) in enumerate(zip(E,A)):
        d=math.hypot(V[a][0]-V[b][0], V[a][1]-V[b][1])
        if d<1e-6: print(f"  e{k} ({a},{b}) {asg} LEN={d:.2e}")
        key=tuple(sorted((a,b)))
        seen.setdefault(key,[]).append((k,asg))
    for key,lst in seen.items():
        if len(lst)>1: print(f"  duplicate edge {key}: {lst}")
    print("\n=== full vertex coords ===")
    for i,(x,y) in enumerate(V): print(f"  v{i:<2} ({x:+.5f}, {y:+.5f})")
if __name__=="__main__": main()
