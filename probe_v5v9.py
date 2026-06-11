"""Exact local crease data at v5 and v9, plus the precise Kawasaki computed
several ways (all creases / M-V only / drop-F-merge-sectors / include-border)."""
import json, math, multiprocessing as mp
QUAD=[{"id":0,"parent_id":None,"length":0},{"id":1,"parent_id":0,"length":0.4},
      {"id":2,"parent_id":1,"length":0.4},{"id":3,"parent_id":0,"length":0.5},
      {"id":4,"parent_id":1,"length":0.5},{"id":5,"parent_id":2,"length":0.5}]
def build(q):
    import headless_treemaker as ht
    e=ht.HeadlessTreemaker(); e.init_paper(1.0,1.0)
    e.build_tree_from_json(json.dumps(QUAD)); e.run_scale_optimization()
    q.put(e.build_and_export())
def alt(rays):
    rays=sorted(rays); n=len(rays)
    sec=[(rays[(k+1)%n]-rays[k])%360 for k in range(n)]
    return sum(sec[0::2])-sum(sec[1::2]), sec
def main():
    ctx=mp.get_context("spawn"); q=ctx.Queue()
    p=ctx.Process(target=build,args=(q,)); p.start(); p.join(40)
    f=json.loads(q.get()); V=f["vertices_coords"]; E=f["edges_vertices"]; A=f["edges_assignment"]
    inc={i:[] for i in range(len(V))}
    for k,((a,b),asg) in enumerate(zip(E,A)):
        inc[a].append((b,asg,k)); inc[b].append((a,asg,k))
    for vi in (5,9):
        x0,y0=V[vi]
        print(f"\n===== v{vi} at ({x0:.6f},{y0:.6f}) deg={len(inc[vi])} =====")
        rows=[]
        for nb,asg,k in inc[vi]:
            x1,y1=V[nb]
            ang=math.degrees(math.atan2(y1-y0,x1-x0))%360
            dist=math.hypot(x1-x0,y1-y0)
            rows.append((ang,asg,nb,dist))
        for ang,asg,nb,dist in sorted(rows):
            print(f"   {asg}  {ang:9.5f}deg  -> v{nb} (len={dist:.5f})")
        allr=[r[0] for r in rows]
        mvr=[r[0] for r in rows if r[1] in("M","V")]
        a_all,_=alt(allr); a_mv,_=alt(mvr)
        print(f"   Kawasaki(all {len(allr)})={a_all:+.6e}   Kawasaki(M/V {len(mvr)})={a_mv:+.6e}")
        # collinear pairs (180 apart)
        for i in range(len(rows)):
            for j in range(i+1,len(rows)):
                d=abs((rows[i][0]-rows[j][0])%360-180)
                if d<0.05:
                    print(f"   COLLINEAR: {rows[i][1]}@{rows[i][0]:.4f} & {rows[j][1]}@{rows[j][0]:.4f} (dev {d:.4f}deg)")
if __name__=="__main__": main()
