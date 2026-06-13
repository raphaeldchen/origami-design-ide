"""Each catalog case must produce the same verdict as the checked-in baseline.
CRASH/HANG always fail regardless of baseline. An IMPROVEMENT (e.g.
FAIL-LINT -> PASS) also fails until re-blessed — this is intentional, it forces
conscious acknowledgement of the change."""
import json
import os

import pytest

import cases

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "baseline_verdicts.json")) as f:
    BASELINE = json.load(f)


@pytest.mark.parametrize("name", [n for n, _ in cases.CASES])
def test_verdict_matches_baseline(name):
    import runner  # imported here so collection works even if ext is missing
    nodes, pairs = cases.CASES_BY_NAME[name]
    actual = runner.verdict_for(nodes, pairs)
    assert actual not in ("CRASH", "HANG"), f"{name} regressed to {actual}"
    expected = BASELINE.get(name)
    assert expected is not None, f"{name} missing from baseline — run tests/bless.py"
    assert actual == expected, (
        f"{name}: verdict {actual} != baseline {expected}. "
        f"If this change is intended, re-run tests/bless.py and commit the diff."
    )
