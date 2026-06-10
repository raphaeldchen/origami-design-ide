# Handoff: TreeMaker Molecule-Construction Layer

**Status as of 2026-06-10.** The headless TreeMaker engine now compiles a metric
tree all the way to a `.fold` crease pattern, and the full **compile → lint**
pipeline runs end-to-end (Oriedita returns per-vertex Kawasaki/Maekawa errors).
This was unblocked by fixing a chain of **6 regressions** introduced by git
commit `d737e92` ("fix: compiler vs build issues") and siblings, all in
`treemaker/Source/tmModel/tmTreeClasses/`.

**The one thing still blocking real flat-foldability:** the molecule produces
some **odd-degree interior vertices**, which are inherently not flat-foldable.
That is the target for the next session. Everything else (active-path math,
crease wiring, polygon validity, facet construction, crash/hang safety) is done.

---

## 1. Quick start / reproduce

```bash
cd mcp_harness
PYTHON=.venv/bin/python ./build.sh        # builds headless_treemaker*.so (clang++, ~30s)
# debug build with line numbers (same NDEBUG behavior, for lldb):
TM_OPT="-O0 -g" PYTHON=.venv/bin/python ./build.sh

.venv/bin/python probe_broad.py           # structured trees, GUI-style scale-only build
.venv/bin/python probe_lint.py            # compile (both paths) + Oriedita lint
```

**The proven case** (`spine-2branch quad`): root with two spine nodes 1,2; legs
3,4,5 hanging off nodes 0,1,2 (lengths 0.4/0.4/0.5/0.5/0.5). Compiles to a FOLD
of 13 vertices / 31 edges, scale ≈ 0.717. It is NOT yet flat-foldable (see §4).

Key wrapper entry points (`TreemakerWrapper.cpp`):
- `run_scale_optimization()` → scale (circle packing).
- `build_and_export()` — **GUI-style scale-only build** (mirrors Action→Build
  Crease Pattern; NO strain opt). Use this as the default build path.
- `run_strain_optimization_and_export()` — scale+strain path (shares
  `BuildAndExport`).
- `debug_poly_report()` — **diagnostic**: after scale-opt, dumps per-leaf-path
  `A`(ctive)/`B`(order)/`F`(easible)/`Poly`gon flags, lengths, leaf positions,
  nPolys, IsPolygonValid. This is how the feasibility-tolerance bug was found.
  (Temp; safe to remove once the layer is solid.)

---

## 2. Regressions fixed (all `treemaker/Source/tmModel/tmTreeClasses/`)

Method that found them all: `git show ad83e7c:<file>` (initial commit) vs HEAD;
the refactor wave rewrote functions and broke them.

1. **`tmPath.cpp::TreePathCalcLengths`** — computed actual paper length as
   `treeLen*scale` (ignoring node positions); restored
   `mActPaperLength = Mag(front->mLoc - back->mLoc)` and paper-space
   active/feasible tests. *Was: every path trivially "active", polygon partition
   never validated.*
2. **`tmPath.cpp::MakeVertex`** (crease split) — built split creases with the
   bare `tmCrease(mTree)` ctor, wiring crease→vertex but not vertex→crease;
   restored the full ctor `tmCrease(tree,owner,v1,v2,kind)`.
3. **`tmPath.cpp::ConnectSelfVertices`** — wrapped `GetOrMakeCrease()`'s
   **tree-owned** return in `std::unique_ptr`, deleting every axial/gusset/hinge
   crease right after creation. *This was the "crease network does not close into
   facets" bug.* Fix: discard the return, do not wrap.
4. **`tmPath.cpp::TestIsFeasible`** — used `TMFLOAT_TOL` (1e-10) where activity
   uses `IsTiny`/`DistTol()` (1e-4); a binding path landing ~1e-7 short came out
   **active-but-infeasible**, and an infeasible path strips polygon-node status
   from both endpoints (`tmTree::CalcPolygonNetwork:2161`) → cascade → 0 polys.
   Fix: `return actLen >= minLen - DistTol();`. *This was THE dominant
   polygon-validity blocker.*

Crash/hang hardening (the original `TMASSERT`/`TMFAIL` guards are compiled out
under `NDEBUG`; **routines reached via `tmTreeCleaner`'s destructor must
`return`, never `throw`** — throwing from a destructor calls `std::terminate`):

5. **`tmCrease.cpp::CalcBend`** — null-guard the `GetAxialOrGussetCreases()`
   result (`return` on null; destructor context).
6. **`tmFacetOwner.cpp::BuildFacetsFromCreases`** — throw on a dead-ended facet
   walk and on `tooMany>=100` (infinite walk), both fwd and bkd loops. (Not in a
   destructor; throw is fine and surfaces as a clean RuntimeError.)
7. **`tmTree_FacetOrder.cpp::CalcFacetOrder`** — when no source facet exists
   (unbroken cycle), set `mIsFacetDataValid = mIsLocalRootConnectable = false`
   and `return`; `CleanupAfterEdit` then early-outs before CalcFacetColor/CalcFold
   (which would deref the unset facet order). Destructor context → no throw.

Also in the working tree (beneficial, keep): **`tmPoint.h`** — removed a leftover
`~tmPoint()` that did `std::cout` on every destruction (would flood stdout, break
the MCP stdio protocol, and cripple performance).

Modified files: `tmPath.cpp`, `tmCrease.cpp`, `tmFacetOwner.cpp`,
`tmTree_FacetOrder.cpp`, `tmPoint.h` (+ wrapper `TreemakerWrapper.cpp`,
`mcp_harness/build.sh` now honors `TM_OPT`). Not committed — the treemaker dir is
a git repo; `git -C treemaker diff` shows them.

---

## 3. Engine pipeline map (where each stage lives)

```
HeadlessTreemaker::BuildAndExport (TreemakerWrapper.cpp)
  tmTree::BuildPolysAndCreasePattern        tmTree.cpp:1760
    BuildTreePolys                          tmTree.cpp:1725  (polygon outlines)
      -> CleanupAfterEdit                   tmTree.cpp:2612  (runs via tmTreeCleaner dtor)
           TreePathCalcLengths (per path)   tmPath.cpp:754   [fix 1] sets A/F
           CalcBorderNodesAndPaths          tmTree.cpp ~2095 sets B
           CalcPolygonNetwork               tmTree.cpp:2134  sets Poly; snips on infeasible [fix 4 critical here]
           CalcPolygonValidity              tmTree.cpp:2225  -> IsPolygonValid()
    for each poly: BuildPolyContents        tmPoly.cpp       <-- MOLECULE: subpolys/ridges/creases
       tmPath::MakeVertex / GetOrMakeVertex tmPath.cpp       [fix 2]
       tmPath::ConnectSelfVertices          tmPath.cpp:471   [fix 3]
       tmFacetOwner::BuildFacetsFromCreases tmFacetOwner.cpp:206 [fix 6]
    -> CleanupAfterEdit again
         CalcDepthAndBend / tmCrease::CalcBend tmCrease.cpp:341 [fix 5]
         CalcFacetOrder                      tmTree_FacetOrder.cpp:515 [fix 7]
            tmPoly::CalcLocalFacetOrder / BuildCorridorLinks  tmPoly.cpp  <-- HANGS on degenerate cases
  ExportFold (vertices_coords + creases->edges)  TreemakerWrapper.cpp
```

`tmPoly.cpp` is git-**untouched** (only the initial commit), so any remaining
defect there is most likely driven by bad data from the `tmPath`/`tmVertex`
helpers it calls — i.e. the same class of regression already seen — rather than
by `tmPoly` itself.

---

## 4. THE NEXT TASK: odd-degree interior vertices

**Symptom.** `spine-2branch quad` compiles, but Oriedita reports ~10 vertex
violations (7 Kawasaki / 3 Maekawa). Direct angle measurement of the FOLD:

```
interior vertex   degree   Kawasaki alt-sum (want 0°)
  v4,v5,v9          6        0.00   <- correct, flat-foldable
  v10,v11,v12       (even)   0.00   <- correct
  v2,v3,v7,v8       5        180.0  <- WRONG: odd degree => not flat-foldable
```

So the molecule geometry is **mostly correct** (half the interior vertices
satisfy Kawasaki exactly — rules out a numeric/convergence cause), with a
discrete **topology** defect: some interior vertices come out degree-5. A
flat-foldable interior vertex must have **even** degree. Each bad vertex is
missing (or has one spurious) incident crease.

**Hypothesis.** A missing-crease defect in subpoly / ridge / gusset / hinge
generation inside `tmPoly::BuildPolyContents` and the `tmPath` helpers it calls
(`MakeVertex`, `GetOrMakeVertex`, `ConnectSelfVertices`, and the ridge/hinge
crease creation). Same shape as fix 3 (a crease that should exist isn't being
created or is being dropped). NOT necessarily in `tmPoly.cpp` itself (untouched);
diff the helpers it calls.

**Concrete investigation plan (next session):**
1. Use `debug_poly_report()` plus a NEW diagnostic that, after a successful
   build, dumps every interior `tmVertex`: its location, `mCreases.size()`, and
   each incident crease's `Kind` (axial/gusset/ridge/hinge/pseudohinge) and
   fold. Identify exactly which crease type is missing at the degree-5 vertices.
2. `git diff ad83e7c HEAD` the molecule-construction helpers and compare against
   the crash/fix pattern: `tmPath.cpp` ridge/hinge functions,
   `tmVertex.cpp`/`.h`, and any `GetOrMakeCrease`/`MakeCrease` callers in
   `tmPoly.cpp`'s build path. Look for: (a) more `unique_ptr`-wrapped tree-owned
   returns (premature delete — `grep -rn unique_ptr` in tmTreeClasses; only
   MakeVertex's, which correctly `.release()`s, should remain), (b) loops that
   were re-indexed/range-for'd and now skip an element, (c) dropped
   `vertex->mCreases` back-links.
3. Cross-check against TreeMaker's `change_log.txt` for the expected crease set
   of a known molecule (e.g. a bird-base quadrant) to know the correct degree.
4. Re-run `probe_lint.py`; success = a tree whose FOLD returns "Flat-foldable"
   (or only M/V-fixable, which Oriedita can auto-resolve).

---

## 5. Secondary issues (robustness, lower priority)

- **Infinite loop / hang** in `tmPoly::CalcLocalFacetOrder()` /
  `BuildCorridorLinks()` on degenerate highly-symmetric topologies (e.g. the
  classic 4-flap star = single square poly). Found via `sample <pid>`. Needs a
  bounded-iteration guard, but these run in the `tmTreeCleaner` **destructor**
  path → must set an invalidity flag and `return`, NOT throw. (Server-side spawn
  isolation already turns the hang into a 60s timeout, so it's contained, just
  slow.)
- A few trees still SIGSEGV (`-11`), e.g. `5-leaf caterpillar` scale path — not
  yet localized (`lldb -O0 -g`, drive past the dyld exec stops with `continue`).
- `run_strain_optimization_and_export` is the wrong default (perturbs the
  uniaxial optimum); keep `build_and_export` (scale-only) as primary.

## 6. Diagnostics left in the tree
- `mcp_harness/probe_broad.py` — structured trees, scale-only.
- `mcp_harness/probe_lint.py` — compile (both paths) + Oriedita lint.
- `mcp_harness/probe_scale_only.py`, `probe_trees.py` — earlier sweeps.
- `HeadlessTreemaker::debug_poly_report()` — per-path flag dump (temp).
- lldb recipe: `TM_OPT="-O0 -g" ./build.sh`, then
  `lldb -b -s cmds.txt -- .venv/bin/python repro.py` with cmds = `process
  launch` + several `continue` + `bt`. (Optimized builds mis-symbolicate; always
  reconfirm a crash site with the `-O0 -g` build.)

Related memory: `treemaker-molecule-build-fragility`, `agent-orchestrator-tier2`,
`headless-treemaker-build-recipe`, `oriedita-linter-slice`.
