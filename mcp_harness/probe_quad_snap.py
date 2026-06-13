"""DECISIVE: is the spine-2branch quad's lint failure precision or structural?"""
import json, math, multiprocessing as mp
import linter_server

QUAD=[{"id":0,"parent_id":None,"length":0},{"id":1,"parent_id":0,"length":0.4},
      {"id":2,"parent_id":1,"length":0.4},{"id":3,"parent_id":0,"length":0.5},
      {"id":4,"parent_id":1,"length":0.5},{"id":5,"parent_id":2,"length":0.5}]

def build(q):
    import headless_treemaker as ht
    e=ht.HeadlessTreemaker(); e.init_paper(1.0,1.0)
    e.build_tree_from_json(json.dumps(QUAD)); e.run_scale_optimization()
    q.put(e.build_and_export())

def first(r,n=1): return "\n      ".join(r.splitlines()[:n])

def main():
    ctx=mp.get_context("spawn"); q=ctx.Queue()
    p=ctx.Process(target=build,args=(q,)); p.start(); p.join(40)
    f=json.loads(q.get())
    V=f["vertices_coords"]; E=f["edges_vertices"]; A=f["edges_assignment"]

    print("=== SNAP TEST (quad) ===")
    print("  as-is   :", first(linter_server.validate_flat_foldability(json.dumps(f))))
    for ndp in (4,3,2):
        g=dict(f); g["vertices_coords"]=[[round(x,ndp),round(y,ndp)] for x,y in V]
        print(f"  snap {ndp}dp :", first(linter_server.validate_flat_foldability(json.dumps(g))))

    inc={i:[] for i in range(len(V))}
    for (a,b),asg in zip(E,A):
        inc[a].append((b,asg)); inc[b].append((a,asg))
    print("\n=== Vertices incident to F (flat) creases ===")
    for vi in range(len(V)):
        asgs=[asg for _,asg in inc[vi]]
        if "F" in asgs:
            rays=sorted((math.degrees(math.atan2(V[n][1]-V[vi][1],V[n][0]-V[vi][0]))%360, asg)
                        for n,asg in inc[vi])
            print(f"  v{vi:<2} deg={len(asgs)} M/V={sum(a in('M','V') for a in asgs)} "
                  f"F={asgs.count('F')} B={asgs.count('B')}")
            for ang,asg in rays:
                print(f"        {asg}  {ang:7.3f}deg")

    print("\n=== F-removed linter ===")
    keep=[i for i,asg in enumerate(A) if asg!="F"]
    h=dict(f); h["edges_vertices"]=[E[i] for i in keep]; h["edges_assignment"]=[A[i] for i in keep]
    if "edges_foldAngle" in f: h["edges_foldAngle"]=[f["edges_foldAngle"][i] for i in keep]
    print("  F-removed:", first(linter_server.validate_flat_foldability(json.dumps(h))))

if __name__=="__main__":
    main()
