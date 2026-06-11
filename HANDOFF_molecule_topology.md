# Handoff: TreeMaker Molecule-Construction Layer

**Status as of 2026-06-10.** The headless TreeMaker engine now compiles a metric
tree all the way to a `.fold` crease pattern, and the full **compile → lint**
pipeline runs end-to-end (Oriedita returns per-vertex Kawasaki/Maekawa errors).
This was unblocked by fixing a chain of **7 regressions** introduced by git
commit `d737e92` ("fix: compiler vs build issues") and siblings, all in
`treemaker/Source/tmModel/tmTreeClasses/`.

## UPDATE (this session): the "odd-degree vertex" was a MISDIAGNOSIS — fixed.

The prior handoff blamed **odd-degree interior vertices**. That was wrong. Direct
measurement (new wrapper diagnostic `debug_vertex_report`) showed the genuine
INTERIOR vertices were already **even-degree and satisfied Kawasaki exactly**
(alt-sum = 0 over all incident creases). The degree-5 vertices the prior handoff
called "interior" are actually **border** vertices (engine `IsBorderVertex()==1`,
carrying `BORDER`-fold creases), where Kawasaki does not apply.

**The actual root cause (regression #7, now fixed):** `tmPath::MakeVertex` was
**double-listing every path-owned vertex** in `mOwnedVertices`. The `tmVertex`
constructor already self-registers with its owner (`tmVertex.cpp:96
mVertexOwner->mOwnedVertices.push_back(this)`), but a refactor added an *explicit*
`mOwnedVertices.push_back(theVertex.release())` on top of it. The duplicate then
flowed into `tmPoly::GetRidgelineVertices` (line 639 asserts, debug-only, that
ridgeline vertices are never double-listed) and `tmPath::ConnectSelfVertices`,
which creased **consecutive identical vertices** together → **zero-length
self-loop creases** (`GetOrMakeCrease(v, v)`; `tmCrease.cpp:92` asserts, debug-
only, `aVertex1 != aVertex2`). The causal chain to the lint failures:

```
double push_back  ->  vertex listed 2x in mOwnedVertices
                  ->  self-loop creases (9 of them on spine-2branch quad)
                  ->  GetAxialOrGussetCreases() returns a self-loop as a "flank"
                  ->  CalcBend sees depth2==depth3, mislabels hinge bend
                  ->  CalcColor parity inverts (facet two-coloring inconsistent)
                  ->  CalcFold emits FLAT for structural creases (even ridges: RF)
                  ->  Oriedita drops F edges -> bogus Kawasaki/Maekawa failures
```

**The fix** (one statement, `tmPath.cpp::MakeVertex`): drop the redundant
`mOwnedVertices.push_back`; let the constructor register the vertex (matches the
pristine `ad83e7c` code). Results on `spine-2branch quad`: **31→22 creases**, all
9 self-loops gone, lint **10→2 violations**, interior vertex `v4` now perfectly
flat-foldable, all interior vertices satisfy Kawasaki+Maekawa by direct math.
Side effects: the **classic 4-flap star now BUILDS** (it previously HUNG in
`CalcLocalFacetOrder`, §5 below — the self-loops were corrupting the corridor
graph), and **4-flap H-shape (strain) now compiles** (was a 60 s timeout).

## Remaining (NEW, separate issue): scale-only base is not fully converged.

The residual lint violations are **numerical precision, not topology**. The
4-flap star's center is a textbook flat-foldable vertex (8 creases at 45°), yet
its measured Kawasaki alt-sum is **−0.0001°**, not 0 — the scale-only ALM
optimizer converges to ~1e-4°, which exceeds Oriedita's angular tolerance.
**Proof:** snapping the star's coords to their true grid (`round(x,4)`) makes
Oriedita return **Pass** (`probe_snap.py`); a hand-built perfect 3M1V vertex also
Passes (so the face-less FOLD interface is fine and Oriedita is not the problem).
Non-grid bases (scale 0.717…) can't be snapped to true positions, so they still
show ~1e-4° residuals. **Next task = drive the base to a true uniaxial optimum**
(tighter ALM convergence, active-path/angle conditions, or a snap-to-uniaxial
post-process) so interior-vertex angles are exact. This is the §5 "not at a
complete uniaxial optimum" item, now isolated as THE remaining blocker.

New wrapper diagnostics (kept; match the `debug_poly_report` pattern):
`debug_vertex_report()` (per-vertex border/interior, degree, incident crease
Kind+Fold), `debug_crease_report()` (per-crease facet colors/orders — finds
FLAT-but-should-fold creases). Probes: `probe_vertex.py`, `probe_kawasaki.py`
(direct Kawasaki/Maekawa from the FOLD), `probe_crease.py`, `probe_snap.py`
(demonstrates the convergence-precision residual).

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

7. **`tmPath.cpp::MakeVertex`** (THIS session) — removed a redundant explicit
   `mOwnedVertices.push_back(theVertex.release())` that double-listed every
   path-owned vertex on top of the `tmVertex` constructor's self-registration.
   The duplicate produced zero-length self-loop creases that corrupted the
   bend/facet-color/fold pipeline. *This was THE flat-foldability blocker — see
   the UPDATE block at the top.* `unique_ptr` ownership was the wrong model here:
   the tree owns all parts via its part hierarchy, not the local scope.

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

## 4. [SUPERSEDED — see the UPDATE block at the top] odd-degree interior vertices

> **This section's diagnosis was WRONG and is kept only for history.** The
> degree-5 vertices below are *border* vertices (Kawasaki-exempt), not interior;
> the genuine interior vertices were already even-degree and Kawasaki-satisfying.
> The real defect was the `tmPath::MakeVertex` double-`push_back` (regression #7),
> now fixed. The actual remaining blocker is **scale-only convergence precision**
> (UPDATE block). Do not chase "odd-degree interior vertices."

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
