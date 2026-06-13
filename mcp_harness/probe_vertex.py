"""TEMP diagnostic driver: dump the per-vertex crease report for the proven
spine-2branch quad case to locate the odd-degree interior vertices."""
import json, multiprocessing as mp


def _worker(q):
    import headless_treemaker as ht
    e = ht.HeadlessTreemaker(); e.init_paper(1.0, 1.0)
    nodes = [{"id": 0, "parent_id": None, "length": 0},
             {"id": 1, "parent_id": 0, "length": 0.4},
             {"id": 2, "parent_id": 1, "length": 0.4},
             {"id": 3, "parent_id": 0, "length": 0.5},
             {"id": 4, "parent_id": 1, "length": 0.5},
             {"id": 5, "parent_id": 2, "length": 0.5}]
    e.build_tree_from_json(json.dumps(nodes))
    e.run_scale_optimization()
    q.put(e.debug_vertex_report())


def main():
    ctx = mp.get_context("spawn"); q = ctx.Queue()
    p = ctx.Process(target=_worker, args=(q,)); p.start(); p.join(40)
    if p.is_alive():
        p.terminate(); p.join(); print("TIMEOUT"); return
    print(q.get() if not q.empty() else f"crash exit={p.exitcode}")


if __name__ == "__main__":
    main()
