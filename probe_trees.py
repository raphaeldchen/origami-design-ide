"""One-off probe: sweep candidate metric trees for the simplest that compiles.

Reuses server._run_isolated + server._worker_full_base so every trial runs in a
spawned child (a molecule-build SIGSEGV fails that trial, not the sweep). Prints
a PASS/FAIL line per candidate; on PASS reports vertex/edge counts from the FOLD.
"""

from __future__ import annotations

import json

import server  # imports headless_treemaker, inserts mcp_harness on sys.path


def _summarize(fold_str: str) -> str:
    try:
        d = json.loads(fold_str)
        v = len(d.get("vertices_coords", []))
        e = len(d.get("edges_vertices", []))
        f = len(d.get("faces_vertices", []))
        return f"vertices={v} edges={e} faces={f}"
    except Exception as exc:
        return f"(could not parse FOLD: {exc})"


# (name, tree_nodes, symmetric_pairs) -- simplest first.
CANDIDATES: list[tuple[str, list[dict], list[list[int]]]] = [
    (
        "2-flap (root + 2 equal leaves)",
        [{"id": 0, "parent_id": None, "length": 0},
         {"id": 1, "parent_id": 0, "length": 1.0},
         {"id": 2, "parent_id": 0, "length": 1.0}],
        [[1, 2]],
    ),
    (
        "4-flap star (root + 4 equal leaves, 2 sym pairs)",
        [{"id": 0, "parent_id": None, "length": 0},
         {"id": 1, "parent_id": 0, "length": 1.0},
         {"id": 2, "parent_id": 0, "length": 1.0},
         {"id": 3, "parent_id": 0, "length": 1.0},
         {"id": 4, "parent_id": 0, "length": 1.0}],
        [[1, 2], [3, 4]],
    ),
    (
        "4-flap star, no symmetry (control)",
        [{"id": 0, "parent_id": None, "length": 0},
         {"id": 1, "parent_id": 0, "length": 1.0},
         {"id": 2, "parent_id": 0, "length": 1.0},
         {"id": 3, "parent_id": 0, "length": 1.0},
         {"id": 4, "parent_id": 0, "length": 1.0}],
        [],
    ),
    (
        "5-flap star (4 legs + head off root)",
        [{"id": 0, "parent_id": None, "length": 0},
         {"id": 1, "parent_id": 0, "length": 1.0},
         {"id": 2, "parent_id": 0, "length": 1.0},
         {"id": 3, "parent_id": 0, "length": 1.0},
         {"id": 4, "parent_id": 0, "length": 1.0},
         {"id": 5, "parent_id": 0, "length": 1.0}],
        [[1, 2], [3, 4]],
    ),
    (
        "quadruped: spine + 2 junctions (agent's last shape)",
        [{"id": 0, "parent_id": None, "length": 0},
         {"id": 1, "parent_id": 0, "length": 0.1},   # rear junction
         {"id": 2, "parent_id": 0, "length": 0.1},   # front junction
         {"id": 3, "parent_id": 1, "length": 1.0},   # rear-left leg
         {"id": 4, "parent_id": 1, "length": 1.0},   # rear-right leg
         {"id": 5, "parent_id": 2, "length": 1.0},   # front-left leg
         {"id": 6, "parent_id": 2, "length": 1.0},   # front-right leg
         {"id": 7, "parent_id": 2, "length": 0.8}],  # head
        [[3, 4], [5, 6]],
    ),
]


def main() -> None:
    print(f"Probing {len(CANDIDATES)} candidate trees (1x1 paper)...\n")
    first_pass = None
    for name, nodes, pairs in CANDIDATES:
        out = server._run_isolated(
            server._worker_full_base, json.dumps(nodes), pairs, 1.0, 1.0
        )
        if out.startswith("ERROR:"):
            print(f"FAIL  {name}\n        {out.splitlines()[0][:160]}\n")
        else:
            print(f"PASS  {name}\n        {_summarize(out)}\n")
            if first_pass is None:
                first_pass = (name, nodes, pairs, out)

    if first_pass:
        name, nodes, pairs, fold = first_pass
        print(f"=> Simplest packing tree: {name}")
        with open("/tmp/good_base.fold", "w") as fh:
            fh.write(fold)
        with open("/tmp/good_tree.json", "w") as fh:
            json.dump({"tree_nodes": nodes, "symmetric_pairs": pairs}, fh, indent=2)
        print("   FOLD -> /tmp/good_base.fold ; tree -> /tmp/good_tree.json")
    else:
        print("=> No candidate packed. The molecule builder rejects all of these.")


if __name__ == "__main__":
    main()
