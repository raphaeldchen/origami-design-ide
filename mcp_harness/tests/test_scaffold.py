"""Smoke tests: the catalog is well-formed and the spawn runner can compile a
known-good tree end-to-end. Proves the import contract + isolation work before
the real regression assertions are layered on."""
import cases
import runner


def test_catalog_nonempty_and_unique():
    names = [name for name, _ in cases.CASES]
    assert len(names) >= 16  # catalog currently has 18; guard against accidental truncation
    assert len(names) == len(set(names)), "duplicate case names"
    for name in cases.GOLDEN_CASE_NAMES:
        assert name in cases.CASES_BY_NAME, f"golden case {name} missing from catalog"


def test_star4_compiles_and_passes():
    nodes, pairs = cases.CASES_BY_NAME["star-4"]
    st, payload = runner.compile_tree(nodes, pairs)
    assert st == "ok", f"expected ok, got {st}: {payload}"
    assert runner.lint(payload) == "Pass"
