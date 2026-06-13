"""Prove the server's export-path bug: the strain worker (what server.py uses)
vs a scale-only worker (what probe_verify uses) on the SAME known-good trees.
"""
import json
import server  # reuse the real isolated-spawn machinery + the strain worker
import linter_server


def _scale_only_worker(queue, tree_nodes_json, pairs, pw, ph):
    try:
        import headless_treemaker as ht
        e = ht.HeadlessTreemaker(); e.init_paper(pw, ph)
        e.build_tree_from_json(tree_nodes_json)
        for a, b in pairs:
            e.apply_symmetry(int(a), int(b))
        e.run_scale_optimization()
        queue.put(("ok", e.build_and_export()))
    except Exception as exc:
        queue.put(("err", str(exc)))


def N(i, p, l):
    return {"id": i, "parent_id": p, "length": l}


CASES = {
    "4-flap star": ([N(0, None, 0), N(1, 0, 1.0), N(2, 0, 1.0),
                     N(3, 0, 1.0), N(4, 0, 1.0)], []),
    "H-shape":     ([N(0, None, 0), N(1, 0, 0.4), N(2, 0, 0.5), N(3, 0, 0.5),
                     N(4, 1, 0.5), N(5, 1, 0.5)], [[2, 3], [4, 5]]),
}


def verdict(fold):
    if fold.startswith("ERROR:"):
        return fold[:55]
    return linter_server.validate_flat_foldability(fold).splitlines()[0]


def main():
    for name, (nodes, pairs) in CASES.items():
        nj = json.dumps(nodes)
        strain = server._run_isolated(server._worker_full_base, nj, pairs, 1.0, 1.0)
        scale = server._run_isolated(_scale_only_worker, nj, pairs, 1.0, 1.0)
        print(f"{name:14s} STRAIN(server)-> {verdict(strain):42s} | "
              f"SCALE(fix)-> {verdict(scale)}")


if __name__ == "__main__":
    main()
