"""The engine must be deterministic: compiling the same tree twice (same
machine) yields identical geometry. Guards against optimizer nondeterminism
that would make goldens flaky and physical output unreproducible."""
import json

import cases
import runner


def test_star4_is_deterministic():
    nodes, pairs = cases.CASES_BY_NAME["star-4"]
    st1, p1 = runner.compile_tree(nodes, pairs)
    st2, p2 = runner.compile_tree(nodes, pairs)
    assert st1 == "ok" and st2 == "ok", f"compile failed: {st1} {st2}"
    g1 = runner.fold_geom(json.loads(p1))
    g2 = runner.fold_geom(json.loads(p2))
    assert g1 == g2, "non-deterministic geometry across identical compiles"
