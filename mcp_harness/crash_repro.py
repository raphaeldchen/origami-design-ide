import headless_treemaker as ht
eng = ht.HeadlessTreemaker()
eng.init_paper(1.0, 1.0)
eng.build_tree_from_json('[{"id":0,"parent_id":null,"length":0},{"id":1,"parent_id":0,"length":1.0},{"id":2,"parent_id":0,"length":1.0},{"id":3,"parent_id":0,"length":1.0}]')
print("scale:", eng.run_scale_optimization(), flush=True)
print(eng.build_and_export()[:60], flush=True)
