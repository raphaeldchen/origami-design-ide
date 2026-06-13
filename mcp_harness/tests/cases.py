"""Canonical Metric Tree catalog — the single source of truth for the
regression suite. Lifted from probe_sweep.py so probes and tests agree.

Each case is (name, nodes, pairs):
  nodes : list of {"id", "parent_id", "length"} dicts (the Metric Tree)
  pairs : list of [a, b] symmetry node-id pairs (may be empty)
"""
from __future__ import annotations


def N(i, parent, length):
    return {"id": i, "parent_id": parent, "length": length}


def star(k, ln=1.0):
    return [N(0, None, 0)] + [N(i, 0, ln) for i in range(1, k + 1)], []


def caterpillar(spine, leaf_len=0.5, spine_len=0.25):
    nodes = [N(0, None, 0)]
    for i in range(1, spine + 1):
        nodes.append(N(i, i - 1, spine_len))
    nxt = spine + 1
    for s in range(0, spine + 1):
        nodes.append(N(nxt, s, leaf_len)); nxt += 1
    return nodes, []


def symmetric_pairs_star(k, ln=1.0):
    nodes, _ = star(k, ln)
    pairs = [[i, i + 1] for i in range(1, k, 2)]
    return nodes, pairs


# The three known-good (PASS end-to-end) cases used for geometry goldens.
HSHAPE = ([N(0, None, 0), N(1, 0, 0.4), N(2, 0, 0.5), N(3, 0, 0.5),
           N(4, 1, 0.5), N(5, 1, 0.5)], [[2, 3], [4, 5]])

QUAD = ([N(0, None, 0), N(1, 0, 0.4), N(2, 1, 0.4), N(3, 0, 0.5),
         N(4, 1, 0.5), N(5, 2, 0.5)], [])

GOLDEN_CASE_NAMES = ["star-4", "hshape", "quad"]

CASES = [
    ("star-3",         star(3)),
    ("star-4",         star(4)),
    ("star-5",         star(5)),
    ("star-6",         star(6)),
    ("star-8",         star(8)),
    ("star-4-sym",     symmetric_pairs_star(4)),
    ("star-6-sym",     symmetric_pairs_star(6)),
    ("cat-spine2",     caterpillar(2)),
    ("cat-spine3",     caterpillar(3)),
    ("cat-spine4",     caterpillar(4)),
    ("cat-spine5",     caterpillar(5)),
    ("cat-long-legs",  caterpillar(3, leaf_len=0.8, spine_len=0.15)),
    ("cat-short-legs", caterpillar(3, leaf_len=0.3, spine_len=0.3)),
    ("uneven-star",    ([N(0, None, 0), N(1, 0, 1.0), N(2, 0, 0.6),
                         N(3, 0, 0.4), N(4, 0, 0.8)], [])),
    ("deep-chain",     ([N(0, None, 0), N(1, 0, 0.3), N(2, 1, 0.3),
                         N(3, 2, 0.3), N(4, 3, 0.3), N(5, 4, 0.5),
                         N(6, 0, 0.5)], [])),
    ("two-level-tree", ([N(0, None, 0), N(1, 0, 0.3), N(2, 0, 0.3),
                         N(3, 1, 0.5), N(4, 1, 0.5), N(5, 2, 0.5),
                         N(6, 2, 0.5)], [])),
    ("hshape",         HSHAPE),
    ("quad",           QUAD),
]

CASES_BY_NAME = {name: payload for name, payload in CASES}
