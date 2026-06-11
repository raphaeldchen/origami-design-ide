"""Ground-truth check: compute Maekawa and Kawasaki directly from the exported
FOLD for the spine-2branch quad, per vertex. Settles whether the INTERIOR
vertices (v4,v5,v9) really satisfy the flat-foldability theorems or not."""
import json, math, multiprocessing as mp

NODES = [{"id": 0, "parent_id": None, "length": 0},
         {"id": 1, "parent_id": 0, "length": 0.4},
         {"id": 2, "parent_id": 1, "length": 0.4},
         {"id": 3, "parent_id": 0, "length": 0.5},
         {"id": 4, "parent_id": 1, "length": 0.5},
         {"id": 5, "parent_id": 2, "length": 0.5}]

# Which FOLD vertex indices the engine marks INTERIOR (from debug_vertex_report).
INTERIOR = {4, 5, 9}


def _worker(q):
    import headless_treemaker as ht
    e = ht.HeadlessTreemaker(); e.init_paper(1.0, 1.0)
    e.build_tree_from_json(json.dumps(NODES))
    e.run_scale_optimization()
    q.put(e.build_and_export())


def main():
    ctx = mp.get_context("spawn"); q = ctx.Queue()
    p = ctx.Process(target=_worker, args=(q,)); p.start(); p.join(40)
    fold = json.loads(q.get())
    V = fold["vertices_coords"]
    E = fold["edges_vertices"]
    A = fold["edges_assignment"]

    # Build incidence: vertex -> list of (neighbor, assignment)
    inc = {i: [] for i in range(len(V))}
    for (a, b), asg in zip(E, A):
        inc[a].append((b, asg))
        inc[b].append((a, asg))

    def kawasaki(rays):
        rays = sorted(rays)
        sectors = [ (rays[(k+1) % len(rays)] - rays[k]) % 360
                    for k in range(len(rays)) ]
        return (sum(sectors[0::2]) - sum(sectors[1::2])) if sectors else 0.0

    for vi in range(len(V)):
        nbrs = inc[vi]
        tag = "INTERIOR" if vi in INTERIOR else "border  "
        x0, y0 = V[vi]
        all_rays, folded_rays = [], []
        for (nb, asg) in nbrs:
            x1, y1 = V[nb]
            ang = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 360
            all_rays.append(ang)
            if asg in ("M", "V"):           # Oriedita treats only M/V as folds
                folded_rays.append(ang)
        nM = sum(1 for _, asg in nbrs if asg == "M")
        nV = sum(1 for _, asg in nbrs if asg == "V")
        nB = sum(1 for _, asg in nbrs if asg == "B")
        nF = sum(1 for _, asg in nbrs if asg == "F")
        print(f"v{vi:<2} [{tag}] deg={len(nbrs)} "
              f"M={nM} V={nV} B={nB} F={nF} | "
              f"Kawasaki(all)={kawasaki(all_rays):8.3f} "
              f"Kawasaki(M/V only)={kawasaki(folded_rays):8.3f} "
              f"Maekawa|M-V|={abs(nM-nV)}")


if __name__ == "__main__":
    main()
