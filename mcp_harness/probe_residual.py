"""Quantify the raw angular residual at the genuinely-flat-foldable centers:
- 4-flap star center
- spine-2branch quad interior vertices
And run the FULL linter on the quad to see WHERE its violations land."""
import json, math, multiprocessing as mp
import linter_server

STAR=[{"id":0,"parent_id":None,"length":0},{"id":1,"parent_id":0,"length":1.0},
      {"id":2,"parent_id":0,"length":1.0},{"id":3,"parent_id":0,"length":1.0},{"id":4,"parent_id":0,"length":1.0}]
QUAD=[{"id":0,"parent_id":None,"length":0},{"id":1,"parent_id":0,"length":0.4},
      {"id":2,"parent_id":1,"length":0.4},{"id":3,"parent_id":0,"length":0.5},
      {"id":4,"parent_id":1,"length":0.5},{"id":5,"parent_id":2,"length":0.5}]

def build(nodes,q):
    import headless_treemaker as ht
    e=ht.HeadlessTreemaker(); e.init_paper(1.0,1.0)
    e.build_tree_from_json(json.dumps(nodes)); e.run_scale_optimization()
    q.put(e.build_and_export())

def get(nodes):
    ctx=mp.get_context("spawn"); q=ctx.Queue()
    p=ctx.Process(target=build,args=(nodes,q)); p.start(); p.join(40)
    return json.loads(q.get())

def residuals(fold, label):
    V=fold["vertices_coords"]; E=fold["edges_vertices"]; A=fold["edges_assignment"]
    inc={i:[] for i in range(len(V))}
    for (a,b),asg in zip(E,A):
        inc[a].append((b,asg)); inc[b].append((a,asg))
    print(f"--- {label}: alt-angle-sum residual at M/V-fold vertices (deg) ---")
    worst=0.0
    for vi in range(len(V)):
        nb=inc[vi]
        rays=sorted(math.degrees(math.atan2(V[n][1]-V[vi][1], V[n][0]-V[vi][0]))%360
                    for n,asg in nb if asg in ("M","V"))
        if len(rays)<4: continue
        sec=[(rays[(k+1)%len(rays)]-rays[k])%360 for k in range(len(rays))]
        alt=sum(sec[0::2])-sum(sec[1::2])
        worst=max(worst,abs(alt))
        print(f"  v{vi:<2} deg(M/V)={len(rays)} alt-sum={alt:+.6e}")
    print(f"  WORST |alt-sum| = {worst:.3e} deg")

def first3(r): return "\n    ".join(r.splitlines()[:4])

if __name__=="__main__":
    star=get(STAR); quad=get(QUAD)
    residuals(star,"STAR center")
    residuals(quad,"QUAD interior")
    print("\n=== FULL linter on QUAD ===")
    print("   ", first3(linter_server.validate_flat_foldability(json.dumps(quad))))
