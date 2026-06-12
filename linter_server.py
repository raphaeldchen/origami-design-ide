"""
MCP server for the AI-Driven Origami IDE backend — the Static Linter (Tier 3).

Exposes Oriedita's flat-foldability engine to the AI agent. The agent sends a
.fold JSON string; this server validates Maekawa / Kawasaki / number-of-folds /
big-little-big at every interior vertex and returns either "Pass" or the list of
vertex violations so the agent can adjust the crease pattern.

The geometry compiler (headless TreeMaker) lives in server.py; this is its
companion validator. Oriedita is Java with no validation CLI, so we drive it via
the OrieditaValidator.java wrapper as a subprocess. The process boundary IS the
crash isolation: a JVM segfault, OOM, or hang on malformed input returns an error
string and never takes down this long-lived MCP server.

Build the Java side first:
    cd mcp_harness && ./build_linter.sh

Run:  python linter_server.py        (stdio transport, for an MCP client)
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import tempfile

from mcp.server.fastmcp import FastMCP

_HERE = os.path.dirname(os.path.abspath(__file__))

# Locate the Oriedita jar (version-agnostic) and the compiled wrapper.
_JARS = sorted(glob.glob(os.path.join(_HERE, "oriedita", "oriedita-*.jar")))
_ORIEDITA_JAR = _JARS[-1] if _JARS else None
_VALIDATOR_CLASS = "OrieditaValidator"

# Wall-clock budget for the Java subprocess. Oriedita's own Check4 caps its
# thread pool at 60s; this outer guard is the real safety net for a wedged JVM.
_VALIDATE_TIMEOUT = 90

mcp = FastMCP("origami-linter")


def _build_hint() -> str:
    return (
        "The Oriedita validator is not built. From the mcp_harness directory run:\n"
        "    ./build_linter.sh\n"
        "(downloads the Oriedita jar and compiles OrieditaValidator.java)."
    )


def _looks_like_fold(obj: object) -> bool:
    """A minimal FOLD-shape check so we never spawn the JVM on non-FOLD JSON.

    The FOLD spec keys we rely on downstream are vertices_coords + edges_vertices.
    A frame can also nest them under file_frames[0], so accept either shape.
    """
    if not isinstance(obj, dict):
        return False

    def has_geometry(d: dict) -> bool:
        return "vertices_coords" in d and "edges_vertices" in d

    if has_geometry(obj):
        return True
    frames = obj.get("file_frames")
    return (
        isinstance(frames, list)
        and len(frames) > 0
        and isinstance(frames[0], dict)
        and has_geometry(frames[0])
    )


# Only Maekawa violations are fixable by reassigning mountain/valley parity. The
# others (Kawasaki angle sum, number-of-folds, big-little-big) are geometry
# problems that no M/V relabeling can repair — the agent must move creases.
_MV_FIXABLE_RULES = {"MAEKAWA"}

# TreeMaker's Universal-Molecule builder can emit spurious degree-2 vertices: a
# point sitting mid-way along one straight fold line (two collinear creases of the
# same mountain/valley assignment), often surrounded only by flat hinges. Such a
# vertex carries NO flat-foldability constraint, but Oriedita does not auto-merge
# it and rejects the pattern. We normalise these away before validation. Both
# transforms below are provably foldability-neutral, so they cannot mask a real
# violation:
#   (1) drop flat (F / unfolded) creases — they impose no fold constraint, and
#       Oriedita already imports F as a non-fold auxiliary line;
#   (2) merge a degree-2 vertex whose two incident creases are COLLINEAR and the
#       SAME assignment — deleting it and joining the two far endpoints changes
#       no angle and no layer order.
# This is a LINT-only normalisation: the canonical FOLD handed to the simulator
# (with every crease intact) is never mutated.
_COLLINEAR_TOL_DEG = 1e-3


def _angle_deg(coords, a: int, b: int) -> float:
    import math
    (x0, y0), (x1, y1) = coords[a], coords[b]
    return math.degrees(math.atan2(y1 - y0, x1 - x0)) % 360


def _normalize_for_foldability(parsed: dict) -> dict:
    """Return a foldability-equivalent copy with flat creases dropped and
    collinear same-assignment degree-2 vertices merged out. Operates only on the
    top-level geometry shape; returns the input unchanged for anything it does not
    recognise, and is fully defensive — any malformed field leaves the FOLD as-is
    so we never turn a checkable pattern into an uncheckable one."""
    try:
        V = parsed.get("vertices_coords")
        EV = parsed.get("edges_vertices")
        EA = parsed.get("edges_assignment")
        if not (isinstance(V, list) and isinstance(EV, list)
                and isinstance(EA, list) and len(EV) == len(EA)):
            return parsed

        # (1) drop flat creases
        edges = [[list(e), a] for e, a in zip(EV, EA) if a != "F"]

        # (2) iteratively merge collinear same-assignment deg-2 vertices
        changed = True
        while changed:
            changed = False
            inc: dict[int, list[int]] = {}
            for ei, (e, _a) in enumerate(edges):
                inc.setdefault(e[0], []).append(ei)
                inc.setdefault(e[1], []).append(ei)
            for v, eids in inc.items():
                if len(eids) != 2:
                    continue
                i1, i2 = eids
                (e1, a1), (e2, a2) = edges[i1], edges[i2]
                if a1 != a2:
                    continue
                n1 = e1[1] if e1[0] == v else e1[0]
                n2 = e2[1] if e2[0] == v else e2[0]
                if n1 == n2:
                    continue
                dev = abs((_angle_deg(V, v, n1) - _angle_deg(V, v, n2)) % 360 - 180)
                if dev > _COLLINEAR_TOL_DEG:
                    continue
                edges[i1] = [[n1, n2], a1]
                del edges[i2]
                changed = True
                break

        # nothing removed and no flat creases dropped → hand back the original
        if len(edges) == len(EV):
            return parsed

        # re-index, dropping vertices no edge references any more
        used = sorted({x for e, _ in edges for x in e})
        remap = {old: new for new, old in enumerate(used)}
        out = dict(parsed)
        out["vertices_coords"] = [V[i] for i in used]
        out["edges_vertices"] = [[remap[e[0]], remap[e[1]]] for e, _ in edges]
        out["edges_assignment"] = [a for _, a in edges]
        # foldAngle / orders no longer line up with the re-indexed edges; drop the
        # ones that are now stale so the JVM does not read mismatched arrays.
        for stale in ("edges_foldAngle", "faces_vertices", "faceOrders",
                      "edgeOrders"):
            out.pop(stale, None)
        return out
    except Exception:
        return parsed


def _violation_hint(rule: str, color: str) -> str:
    """Translate Oriedita's (rule, color) enums into a plain, actionable hint."""
    if rule == "MAEKAWA":
        if color == "NOT_ENOUGH_VALLEY":
            return ("MAEKAWA — too many mountains here (Maekawa's theorem needs "
                    "|M-V|=2); flip one incident M crease to V.")
        if color == "NOT_ENOUGH_MOUNTAIN":
            return ("MAEKAWA — too many valleys here (Maekawa's theorem needs "
                    "|M-V|=2); flip one incident V crease to M.")
        return (f"MAEKAWA — mountain/valley counts violate |M-V|=2 ({color}); "
                "adjust incident M/V assignments.")
    if rule == "ANGLES":
        return ("ANGLES (Kawasaki) — angles around this vertex don't alternate-sum "
                "to 180°; cannot be fixed by reassigning M/V — adjust crease positions.")
    if rule == "NUMBER_OF_FOLDS":
        return ("NUMBER_OF_FOLDS — a crease terminates in the paper interior or the "
                "vertex has an invalid number of folds; not an M/V issue.")
    if rule == "LITTLE_BIG_LITTLE":
        return ("LITTLE_BIG_LITTLE — the angle sequence around this vertex violates "
                "the big-little-big lemma; geometry issue, not fixable by M/V.")
    return f"{rule} — {color}"


def _format_violations(stdout: str) -> str:
    """Turn the wrapper's tab-delimited VIOLATION lines into agent-readable text.

    Each line carries a plain-language remediation hint, and the summary
    separates M/V-fixable vertices from geometry problems so the agent knows
    which ones it can resolve by relabeling creases.
    """
    lines = []
    mv_fixable = 0
    geometry = 0
    for raw in stdout.splitlines():
        if not raw.startswith("VIOLATION"):
            continue
        parts = raw.split("\t")
        # VIOLATION \t rule \t color \t x \t y
        if len(parts) != 5:
            lines.append(f"  (unparseable violation line: {raw!r})")
            continue
        _, rule, color, x, y = parts
        try:
            loc = f"({float(x):.3f}, {float(y):.3f})"
        except ValueError:
            loc = f"({x}, {y})"
        if rule in _MV_FIXABLE_RULES:
            mv_fixable += 1
        else:
            geometry += 1
        lines.append(f"  Vertex {loc}: {_violation_hint(rule, color)}")

    if not lines:
        # Engine said not-pass but emitted nothing we could parse.
        return "ERROR: validator reported a failure but produced no readable violations."

    count = len(lines)
    header = (
        f"Flat-foldability FAILED: {count} vertex "
        f"{'violation' if count == 1 else 'violations'} "
        f"({mv_fixable} M/V-fixable, {geometry} geometry).\n"
    )
    return header + "\n".join(lines)


@mcp.tool()
def validate_flat_foldability(fold_json_string: str) -> str:
    """Validate a .fold crease pattern for flat-foldability via Oriedita.

    Runs Oriedita's per-interior-vertex checks (Maekawa's theorem, Kawasaki's
    angle theorem, the number-of-folds rule, and the big-little-big lemma) on the
    supplied FOLD geometry.

    Args:
        fold_json_string: the full contents of a .fold file as a JSON string.

    Returns:
        "Pass" if every vertex is flat-foldable. Otherwise a human-readable list
        of violating vertices, each as "Vertex (x, y): <rule> — <mountain/valley
        hint>". Any input or engine problem returns a string starting with
        "ERROR: " so the agent can react instead of the server crashing.
    """
    if _ORIEDITA_JAR is None or not os.path.isfile(_ORIEDITA_JAR):
        return "ERROR: " + _build_hint()
    if not os.path.isfile(os.path.join(_HERE, f"{_VALIDATOR_CLASS}.class")):
        return "ERROR: " + _build_hint()

    # Gate 1: must be JSON at all.
    try:
        parsed = json.loads(fold_json_string)
    except json.JSONDecodeError as exc:
        return f"ERROR: input is not valid JSON ({exc})."

    # Gate 2: must look like a FOLD file. Never hand the JVM non-FOLD garbage.
    if not _looks_like_fold(parsed):
        return (
            "ERROR: input is valid JSON but not a FOLD file "
            "(missing 'vertices_coords' / 'edges_vertices')."
        )

    # Normalise away foldability-neutral artefacts (flat creases, spurious
    # collinear degree-2 vertices) that Oriedita rejects but that carry no real
    # constraint. Defensive: returns the input untouched if it cannot apply.
    fold_to_check = json.dumps(_normalize_for_foldability(parsed))

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".fold", delete=False, dir=_HERE
        ) as fh:
            fh.write(fold_to_check)
            tmp_path = fh.name

        classpath = _ORIEDITA_JAR + os.pathsep + _HERE
        try:
            # -Dtinylog.level=off silences Oriedita's tinylog INFO lines, which
            # otherwise print to stdout and pollute our verdict protocol.
            proc = subprocess.run(
                ["java", "-Dtinylog.level=off", "-cp", classpath,
                 _VALIDATOR_CLASS, tmp_path],
                capture_output=True,
                text=True,
                timeout=_VALIDATE_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return (
                f"ERROR: validation timed out after {_VALIDATE_TIMEOUT}s. The crease "
                "pattern may be pathologically large or malformed."
            )
        except FileNotFoundError:
            return "ERROR: 'java' not found on PATH. Install a JDK (Temurin 17)."

        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        # The wrapper exits 0 on a clean verdict (PASS or VIOLATIONs) and 1 on
        # any load/engine error (reported as an ERROR\t line on stderr). Scan
        # lines rather than match exactly, so any stray log output is tolerated.
        if proc.returncode != 0:
            for line in stderr.splitlines():
                if line.startswith("ERROR\t"):
                    return "ERROR: " + line[len("ERROR\t"):]
            # JVM crash / signal — no clean ERROR line. Server still survives.
            return (
                "ERROR: the Oriedita validator subprocess failed "
                f"(exit code {proc.returncode}). "
                f"stderr: {stderr or '<empty>'}"
            )

        out_lines = stdout.splitlines()
        if any(line.startswith("VIOLATION") for line in out_lines):
            return _format_violations(stdout)
        if any(line.strip() == "PASS" for line in out_lines):
            return "Pass"

        return (
            "ERROR: unexpected validator output. "
            f"stdout: {stdout!r} stderr: {stderr!r}"
        )
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


if __name__ == "__main__":
    mcp.run()
