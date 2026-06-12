"""The three known-good cases must reproduce their golden FOLD geometry:
vertices within an absolute tolerance (CI runs on a different machine than the
box that blessed the goldens); edge topology and mountain/valley assignment
exact. Metadata (file_*/frame_*) is ignored by construction (goldens store only
runner.GEOM_KEYS)."""
import json
import os

import pytest

import cases
import runner

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN_DIR = os.path.join(HERE, "goldens")
VERTEX_TOL = 1e-6


def _load_golden(name):
    with open(os.path.join(GOLDEN_DIR, f"{name}.fold")) as f:
        return json.load(f)


@pytest.mark.parametrize("name", cases.GOLDEN_CASE_NAMES)
def test_geometry_matches_golden(name):
    nodes, pairs = cases.CASES_BY_NAME[name]
    st, payload = runner.compile_tree(nodes, pairs)
    assert st == "ok", f"{name} did not compile: {st} {payload}"
    actual = runner.fold_geom(json.loads(payload))
    golden = _load_golden(name)

    # Exact topology + mountain/valley.
    assert actual["edges_vertices"] == golden["edges_vertices"], \
        f"{name}: edge topology changed"
    assert actual["edges_assignment"] == golden["edges_assignment"], \
        f"{name}: mountain/valley assignment changed"

    # Vertices within tolerance.
    av, gv = actual["vertices_coords"], golden["vertices_coords"]
    assert len(av) == len(gv), f"{name}: vertex count changed {len(av)} != {len(gv)}"
    for i, (a, g) in enumerate(zip(av, gv)):
        assert len(a) == len(g), f"{name}: vertex {i} dimension changed"
        for j, (ac, gc) in enumerate(zip(a, g)):
            assert abs(ac - gc) <= VERTEX_TOL, (
                f"{name}: vertex {i}[{j}] drifted {ac} vs {gc} "
                f"(>{VERTEX_TOL}). If intended, re-run tests/bless.py."
            )
