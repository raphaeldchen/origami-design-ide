"""TEMP: dump per-crease facet colors for spine-2branch quad to locate the
facet-coloring inconsistency that turns structural creases FLAT."""
import json, multiprocessing as mp

NODES = [{"id": 0, "parent_id": None, "length": 0},
         {"id": 1, "parent_id": 0, "length": 0.4},
         {"id": 2, "parent_id": 1, "length": 0.4},
         {"id": 3, "parent_id": 0, "length": 0.5},
         {"id": 4, "parent_id": 1, "length": 0.5},
         {"id": 5, "parent_id": 2, "length": 0.5}]


def _worker(q):
    import headless_treemaker as ht
    e = ht.HeadlessTreemaker(); e.init_paper(1.0, 1.0)
    e.build_tree_from_json(json.dumps(NODES))
    e.run_scale_optimization()
    q.put(e.debug_crease_report())


def main():
    ctx = mp.get_context("spawn"); q = ctx.Queue()
    p = ctx.Process(target=_worker, args=(q,)); p.start(); p.join(40)
    print(q.get() if not q.empty() else f"crash {p.exitcode}")


if __name__ == "__main__":
    main()
