"""Measure Oriedita's Kawasaki angular tolerance directly: one interior vertex
(degree 4, M/V/V/V => Maekawa OK) with a dialable Kawasaki residual; sweep it,
find the Pass->Fail threshold. Settles whether v5(1.6e-5) / v9(4.2e-5) / star(9.6e-5)
all fail purely on precision."""
import json, math
import linter_server

def make_fold(delta_deg):
    """Center interior vertex at origin, 4 creases to square corners at
    45,135,225,(315+delta). Border = the 4 paper edges. Returns FOLD + residual."""
    d = math.radians(315+delta_deg)
    R = 1.0
    corners = [(R*math.cos(math.radians(45)),  R*math.sin(math.radians(45))),
               (R*math.cos(math.radians(135)), R*math.sin(math.radians(135))),
               (R*math.cos(math.radians(225)), R*math.sin(math.radians(225))),
               (R*math.cos(d),                 R*math.sin(d))]
    C = (0.0, 0.0)
    V = [C] + corners                       # v0 center, v1..v4 corners
    E, A = [], []
    for i in range(1,5):                    # center->corner creases  M,V,V,V
        E.append([0,i]); A.append("M" if i==1 else "V")
    for i in range(1,5):                    # border square edges
        E.append([i, 1 + (i%4)]); A.append("B")
    f = {"file_spec":1.1,"frame_attributes":["2D"],
         "vertices_coords":V,"edges_vertices":E,"edges_assignment":A}
    # actual Kawasaki residual at center
    rays=sorted(math.degrees(math.atan2(y,x))%360 for x,y in corners)
    sec=[(rays[(k+1)%4]-rays[k])%360 for k in range(4)]
    return f, (sec[0]-sec[1]+sec[2]-sec[3])

def first(r): return r.splitlines()[0]
print(f"{'delta(deg)':>12} {'Kawasaki resid(deg)':>22}  result")
for delta in (0, 1e-6, 1e-5, 5e-5, 1e-4, 5e-4, 1e-3, 1e-2, 5e-2, 0.1, 0.5):
    f, resid = make_fold(delta)
    res = first(linter_server.validate_flat_foldability(json.dumps(f)))
    verdict = "PASS" if res.startswith("Pass") else "FAIL"
    print(f"{delta:12.6g} {resid:22.6e}  {verdict}   ({res[:42]})")
