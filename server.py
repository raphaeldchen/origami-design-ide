"""
MCP server for the AI-Driven Origami IDE backend (Phase 2).

Exposes the headless TreeMaker engine (compiled C++ pybind module) to an AI
agent. The agent sends an abstract metric tree ("Stick Figure") plus symmetry
constraints; the server builds it natively in C++, runs the full ALM
optimization sequence (scale -> strain), builds the Universal Molecule, and
returns a .fold crease-pattern JSON string.

Two usage modes:
  * One-shot:    draft_and_compile_full_base(tree_nodes, symmetric_pairs)
  * Incremental: new_base -> apply_symmetry / set_edge_strain_fixed -> compile_base

The crash-prone Universal-Molecule build runs in an isolated *spawned* child, so a
SIGSEGV in the legacy facet builder returns an error instead of killing the
server. Spawn (not fork) is required because the FastMCP stdio transport keeps a
daemon thread blocked on stdin; fork copies that thread's held BufferedReader
lock but not the thread, so a forked child deadlocks before its target runs.
Spawn re-execs a clean interpreter, sidestepping the inherited lock entirely.

Run:  python server.py            (stdio transport, for an MCP client)
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys

# Ensure the compiled extension (built alongside this file) is importable.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from mcp.server.fastmcp import FastMCP

try:
    import headless_treemaker as ht  # the compiled C++ pybind module
except ImportError as exc:  # pragma: no cover - surfaced at startup
    raise SystemExit(
        "Could not import 'headless_treemaker'. Build it first:\n"
        "    cd mcp_harness && PYTHON=./.venv/bin/python ./build.sh\n"
        f"Underlying error: {exc}"
    )

mcp = FastMCP("origami-treemaker")

# Per-compile wall-clock budget (seconds) for the isolated worker.
_COMPILE_TIMEOUT = 60

# Parent-side session for the incremental drafting tools. Because spawn cannot
# inherit a live C++ engine object, the session stores the *recipe* (the plain,
# picklable inputs) rather than relying on forked memory; compile_base ships the
# recipe to the worker, which rebuilds the engine from scratch. A live parent
# engine is also kept purely to validate each drafting step eagerly (good early
# errors) — it is never sent to the worker.
_SESSION: dict = {
    "engine": None,          # live parent engine, validation only
    "tree_nodes": None,      # list[dict], the built tree
    "paper_width": 1.0,
    "paper_height": 1.0,
    "pairs": [],             # list[[node_a, node_b]] applied symmetry pairs
    "fixed_edges": [],       # list[int] edge (child-node) ids locked to zero strain
}


# --------------------------------------------------------------------------- #
# Crash-isolated workers (top-level so spawn can pickle them).                 #
#                                                                             #
# Each runs in a fresh interpreter, receives only picklable args, rebuilds its #
# own engine, and puts ("ok", fold_str) or ("err", message) on the queue. A    #
# SIGSEGV in the fragile facet builder simply leaves the queue empty with a    #
# negative exitcode, which the parent translates into a clean error string.    #
# --------------------------------------------------------------------------- #
def _worker_full_base(queue, tree_nodes_json, pairs, paper_width, paper_height):
    """Build -> constrain -> scale-opt -> strain-opt -> export, from scratch."""
    try:
        import headless_treemaker as ht_child

        engine = ht_child.HeadlessTreemaker()
        engine.init_paper(paper_width, paper_height)
        engine.build_tree_from_json(tree_nodes_json)
        for pair in pairs:
            engine.apply_symmetry(int(pair[0]), int(pair[1]))
        engine.run_scale_optimization()
        queue.put(("ok", engine.run_strain_optimization_and_export()))
    except Exception as exc:  # clean C++/Python errors
        queue.put(("err", str(exc)))


def _worker_compile_recipe(queue, recipe):
    """Rebuild a session's engine from its serialized recipe, then compile.

    This is what replaces fork's "inherit the live engine" trick: the full
    drafting history (tree + symmetry pairs + fixed edges + paper) is replayed
    deterministically in the child before optimizing and exporting.
    """
    try:
        import headless_treemaker as ht_child

        engine = ht_child.HeadlessTreemaker()
        engine.init_paper(recipe["paper_width"], recipe["paper_height"])
        engine.build_tree_from_json(recipe["tree_nodes_json"])
        for pair in recipe["pairs"]:
            engine.apply_symmetry(int(pair[0]), int(pair[1]))
        for edge_id in recipe["fixed_edges"]:
            engine.set_edge_strain_fixed(int(edge_id))
        engine.run_scale_optimization()
        queue.put(("ok", engine.run_strain_optimization_and_export()))
    except Exception as exc:
        queue.put(("err", str(exc)))


def _worker_convert_tmd(queue, filepath):
    """Load a GUI-saved Golden Base .tmd/.tmd5 and export its crease pattern."""
    try:
        import headless_treemaker as ht_child

        engine = ht_child.HeadlessTreemaker()
        queue.put(("ok", engine.load_and_export_tmd(filepath)))
    except Exception as exc:
        queue.put(("err", str(exc)))


def _run_isolated(worker_fn, *args) -> str:
    """Run a top-level worker in a spawned child and return its .fold/err string.

    spawn (not fork) is mandatory under the stdio MCP transport: a forked child
    inherits the stdin BufferedReader lock held by the transport's reader thread
    and deadlocks before executing a single line. spawn launches a clean
    interpreter, so the worker must be a top-level (picklable) function taking
    only picklable args — hence the recipe-based session above.

    A child SIGSEGV leaves the result queue empty with a negative exitcode, which
    we report cleanly so the long-lived server survives the legacy facet crash.
    """
    ctx = mp.get_context("spawn")
    queue = ctx.Queue()

    proc = ctx.Process(target=worker_fn, args=(queue, *args))
    proc.start()
    proc.join(_COMPILE_TIMEOUT)

    if proc.is_alive():
        proc.terminate()
        proc.join()
        return f"ERROR: compilation timed out after {_COMPILE_TIMEOUT}s"

    if not queue.empty():
        status, payload = queue.get()
        return payload if status == "ok" else f"ERROR: {payload}"

    return (
        "ERROR: the geometry engine crashed while building the crease pattern "
        f"(exit code {proc.exitcode}). The optimized base is not convergent "
        "enough to build a valid Universal Molecule. Adjust edge lengths or "
        "symmetry/fixed-edge conditions and retry."
    )


# --------------------------------------------------------------------------- #
# One-shot pipeline                                                           #
# --------------------------------------------------------------------------- #
@mcp.tool()
def draft_and_compile_full_base(
    tree_nodes: list[dict],
    symmetric_pairs: list[list[int]] | None = None,
    paper_width: float = 1.0,
    paper_height: float = 1.0,
) -> str:
    """Build, constrain, optimize, and compile a metric tree to a .fold string.

    Full pipeline in one isolated call: build the tree, apply each symmetric
    pair, run ALM scale optimization then strain optimization, build the
    Universal Molecule, and return FOLD JSON.

    Args:
        tree_nodes: list of node dicts (see describe_tree_format).
        symmetric_pairs: list of [node_a, node_b] leaf-node id pairs to mirror
            about the paper's symmetry axis.
        paper_width, paper_height: paper canvas size (default 1x1 square).

    Returns:
        A .fold JSON string, or a string starting with "ERROR: " describing the
        failure so the agent can adjust and retry.
    """
    pairs = symmetric_pairs or []
    return _run_isolated(
        _worker_full_base,
        json.dumps(tree_nodes),
        pairs,
        paper_width,
        paper_height,
    )


# --------------------------------------------------------------------------- #
# Incremental session                                                         #
# --------------------------------------------------------------------------- #
@mcp.tool()
def new_base(
    tree_nodes: list[dict],
    paper_width: float = 1.0,
    paper_height: float = 1.0,
) -> str:
    """Start a new incremental base session and build its tree.

    Follow with apply_symmetry / set_edge_strain_fixed, then compile_base.
    """
    try:
        # Validate eagerly with a live parent engine for good early errors...
        engine = ht.HeadlessTreemaker()
        engine.init_paper(paper_width, paper_height)
        engine.build_tree_from_json(json.dumps(tree_nodes))
        # ...but persist the picklable recipe; the spawned compile worker rebuilds
        # from this, not from the (non-picklable) live engine. Reset prior steps.
        _SESSION.update(
            engine=engine,
            tree_nodes=tree_nodes,
            paper_width=paper_width,
            paper_height=paper_height,
            pairs=[],
            fixed_edges=[],
        )
        return f"OK: base session created with {len(tree_nodes)} nodes."
    except Exception as exc:
        return f"ERROR: {exc}"


@mcp.tool()
def apply_symmetry(node_a: int, node_b: int) -> str:
    """Pair two leaf nodes as mirror images about the paper's symmetry axis.

    Operates on the current session (call new_base first).
    """
    engine = _SESSION.get("engine")
    if engine is None:
        return "ERROR: no active base; call new_base first."
    try:
        engine.apply_symmetry(int(node_a), int(node_b))
        # Record into the recipe so the spawned worker can replay it.
        _SESSION["pairs"].append([int(node_a), int(node_b)])
        return f"OK: nodes {node_a} and {node_b} paired about symmetry line."
    except Exception as exc:
        return f"ERROR: {exc}"


@mcp.tool()
def set_edge_strain_fixed(edge_id: int) -> str:
    """Lock an edge's length (edge_id = the child node id of the edge to fix).

    Operates on the current session (call new_base first).
    """
    engine = _SESSION.get("engine")
    if engine is None:
        return "ERROR: no active base; call new_base first."
    try:
        engine.set_edge_strain_fixed(int(edge_id))
        # Record into the recipe so the spawned worker can replay it.
        _SESSION["fixed_edges"].append(int(edge_id))
        return f"OK: edge above node {edge_id} fixed (zero strain)."
    except Exception as exc:
        return f"ERROR: {exc}"


@mcp.tool()
def compile_base() -> str:
    """Optimize (scale -> strain) and compile the current session to a .fold."""
    if _SESSION.get("engine") is None:
        return "ERROR: no active base; call new_base first."

    # Serialize the full drafting history into a picklable recipe; the spawned
    # worker rebuilds the engine from this and replays every step before
    # optimizing + exporting. No live engine object crosses the process boundary.
    recipe = {
        "tree_nodes_json": json.dumps(_SESSION["tree_nodes"]),
        "pairs": list(_SESSION["pairs"]),
        "fixed_edges": list(_SESSION["fixed_edges"]),
        "paper_width": _SESSION["paper_width"],
        "paper_height": _SESSION["paper_height"],
    }
    return _run_isolated(_worker_compile_recipe, recipe)


# --------------------------------------------------------------------------- #
# Golden Base validation                                                      #
# --------------------------------------------------------------------------- #
@mcp.tool()
def convert_tmd_to_fold(filepath: str) -> str:
    """Convert a GUI-saved 'Golden Base' .tmd/.tmd5 file to FOLD JSON.

    Loads a fully-solved TreeMaker base (saved AFTER Action->Build Crease
    Pattern, in native v5 format) and exports its crease pattern. No
    optimization is run -- this validates the .fold exporter against a known-good
    base. Runs in an isolated child so legacy deserialization crashes are
    contained.

    Args:
        filepath: path to a local .tmd / .tmd5 file.

    Returns:
        A .fold JSON string, or a string starting with "ERROR: ".
    """
    return _run_isolated(_worker_convert_tmd, filepath)


@mcp.tool()
def describe_tree_format() -> str:
    """Return the exact JSON schema the agent must use for `tree_nodes`."""
    example = [
        {"id": 0, "parent_id": None, "length": 0},
        {"id": 1, "parent_id": 0, "length": 1.0},
        {"id": 2, "parent_id": 0, "length": 1.0},
    ]
    return json.dumps(
        {
            "description": (
                "A metric tree (acyclic). One root with parent_id=null; every "
                "other node attaches to a parent that appears earlier in the "
                "list. 'length' is the proportional flap length. Symmetric pairs "
                "must be leaf nodes."
            ),
            "node_fields": {
                "id": "int, required, unique",
                "parent_id": "int or null (null = root)",
                "length": "float > 0 for non-root edges; ignored for root",
                "x": "float, optional initial x on paper",
                "y": "float, optional initial y on paper",
            },
            "example": example,
        },
        indent=2,
    )


if __name__ == "__main__":
    mcp.run()
