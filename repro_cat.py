"""Minimal single-process repro of the 5-leaf caterpillar SIGSEGV (scale path)."""
import json
import headless_treemaker as ht
nodes = [
    {"id":0,"parent_id":None,"length":0},
    {"id":1,"parent_id":0,"length":0.25},
    {"id":2,"parent_id":1,"length":0.25},
    {"id":3,"parent_id":2,"length":0.25},
    {"id":4,"parent_id":0,"length":0.5},
    {"id":5,"parent_id":1,"length":0.5},
    {"id":6,"parent_id":2,"length":0.5},
    {"id":7,"parent_id":3,"length":0.5},
]
e = ht.HeadlessTreemaker(); e.init_paper(1.0, 1.0)
e.build_tree_from_json(json.dumps(nodes))
print("scale:", e.run_scale_optimization(), flush=True)
print("exporting...", flush=True)
fold = e.build_and_export()
print("OK", len(json.loads(fold)["vertices_coords"]), flush=True)
