/*******************************************************************************
TreemakerWrapper.cpp

Pybind11 binding that exposes a headless slice of Robert J. Lang's TreeMaker
math engine (vishvish/treemaker, Source/tmModel) to Python. No wxWidgets / GUI.

Pipeline proven by this thin vertical slice:
    JSON metric tree  ->  native tmTree (AddNode branching API)
                      ->  ALM scale optimization (circle packing)
                      ->  Universal Molecule (BuildPolysAndCreasePattern)
                      ->  .fold JSON string

Build notes (see CMakeLists.txt / build.sh): compile against tmModel with NONE
of TMWX / TMDEBUG / TMPROFILE defined, so the engine is pure C++.
*******************************************************************************/

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <map>
#include <vector>
#include <algorithm>
#include <utility>
#include <string>
#include <sstream>
#include <fstream>
#include <iomanip>
#include <cmath>
#include <stdexcept>

// TreeMaker model (umbrella header pulls in tmTree, optimizers, tmNLCO, ...)
#include "tmModel.h"
#include "tmNLCO_alm.h"   // the freely-distributable optimizer backend (ALM)

namespace py = pybind11;

/*
 * Solve the dense linear system A*out = rhs (A is n-by-n, row-major) in place by
 * Gaussian elimination with partial pivoting. Returns false if A is singular to
 * working precision. n is small here (2 * leaf-count, <= ~16), so an O(n^3) dense
 * solve is trivial; we use it for the Gauss-Newton normal equations in
 * ProjectActivePaths.
 */
static bool SolveDense(std::vector<double> A, std::vector<double> rhs,
                       std::size_t n, std::vector<double>& out)
{
  out.assign(n, 0.0);
  for (std::size_t col = 0; col < n; ++col) {
    // Partial pivot: find the row with the largest magnitude in this column.
    std::size_t piv = col;
    double best = std::fabs(A[col * n + col]);
    for (std::size_t r = col + 1; r < n; ++r) {
      double v = std::fabs(A[r * n + col]);
      if (v > best) { best = v; piv = r; }
    }
    if (best < 1e-18) return false;            // singular
    if (piv != col) {
      for (std::size_t c = 0; c < n; ++c)
        std::swap(A[piv * n + c], A[col * n + c]);
      std::swap(rhs[piv], rhs[col]);
    }
    // Eliminate below the pivot.
    double diag = A[col * n + col];
    for (std::size_t r = col + 1; r < n; ++r) {
      double f = A[r * n + col] / diag;
      if (f == 0.0) continue;
      for (std::size_t c = col; c < n; ++c) A[r * n + c] -= f * A[col * n + c];
      rhs[r] -= f * rhs[col];
    }
  }
  // Back-substitution.
  for (std::size_t i = n; i-- > 0;) {
    double s = rhs[i];
    for (std::size_t c = i + 1; c < n; ++c) s -= A[i * n + c] * out[c];
    out[i] = s / A[i * n + i];
  }
  return true;
}

/*
 * Map a TreeMaker crease fold direction onto a FOLD edges_assignment letter.
 *   MOUNTAIN -> "M", VALLEY -> "V", BORDER -> "B", FLAT/anything else -> "F".
 */
static const char* FoldToAssignment(tmCrease::Fold fold)
{
  switch (fold) {
    case tmCrease::MOUNTAIN: return "M";
    case tmCrease::VALLEY:   return "V";
    case tmCrease::BORDER:   return "B";
    case tmCrease::FLAT:     return "F";
    default:                 return "F";
  }
}

/*
 * Translate a CPStatus failure code into a human-readable reason the AI agent
 * can act on. Only called when HasFullCP() is false.
 */
static std::string CPStatusToString(tmTree::CPStatus status)
{
  switch (status) {
    case tmTree::HAS_FULL_CP:
      return "full crease pattern (no error)";
    case tmTree::EDGES_TOO_SHORT:
      return "EDGES_TOO_SHORT: some edges are shorter than allowed; "
             "increase those edge lengths.";
    case tmTree::POLYS_NOT_VALID:
      return "POLYS_NOT_VALID: the polygon network is not valid for this tree.";
    case tmTree::POLYS_NOT_FILLED:
      return "POLYS_NOT_FILLED: polygons are not fully packed/optimal; the tree "
             "likely needs strain optimization or active-path conditions before "
             "a molecule can be built.";
    case tmTree::POLYS_MULTIPLE_IBPS:
      return "POLYS_MULTIPLE_IBPS: multiple inactive-border-path situations.";
    case tmTree::VERTICES_LACK_DEPTH:
      return "VERTICES_LACK_DEPTH: vertex depth could not be resolved.";
    case tmTree::FACETS_NOT_VALID:
      return "FACETS_NOT_VALID: facet ordering is invalid.";
    case tmTree::NOT_LOCAL_ROOT_CONNECTABLE:
      return "NOT_LOCAL_ROOT_CONNECTABLE: local-root connectivity failed.";
    default:
      return "unknown CPStatus";
  }
}

/**********
class HeadlessTreemaker
A single-tree session: init paper, build a tree from JSON, optimize, export FOLD.
**********/
class HeadlessTreemaker {
public:
  HeadlessTreemaker() : mTree(new tmTree()) {}

  ~HeadlessTreemaker() { delete mTree; }

  // Set up the paper canvas. Origami usually uses 1x1; rectangles are allowed.
  void init_paper(double width, double height) {
    if (width <= 0.0 || height <= 0.0)
      throw std::runtime_error("init_paper: width and height must be positive");
    mTree->SetPaperWidth(width);
    mTree->SetPaperHeight(height);
  }

  /*
   * Build the metric tree from a JSON string: a list of node dicts, e.g.
   *   [{"id": 0, "parent_id": null, "length": 0},
   *    {"id": 1, "parent_id": 0, "length": 0.5}, ...]
   * The root has parent_id null and is created first (AddNode with NULL parent).
   * Each non-root node hangs off its parent via a new edge whose length is set
   * from "length". Optional "x"/"y" give an initial placement; otherwise nodes
   * are auto-placed (the optimizer relocates leaf nodes regardless).
   */
  void build_tree_from_json(const std::string& tree_json_string) {
    // Parse with CPython's json module (GIL held inside a pybind call).
    py::object loads = py::module_::import("json").attr("loads");
    py::object parsed = loads(tree_json_string);
    py::list nodes = py::cast<py::list>(parsed);

    if (py::len(nodes) == 0)
      throw std::runtime_error("build_tree_from_json: empty node list");

    mNodeMap.clear();
    mEdgeMap.clear();
    mSymPairs.clear();

    const double w = mTree->GetPaperWidth();
    const double h = mTree->GetPaperHeight();

    // One outer cleaner: defer the (O(n)) CleanupAfterEdit to once at the end
    // instead of after every AddNode/SetLength. tmTreeCleaner is reentrant.
    tmTreeCleaner tc(mTree);

    std::size_t order = 0;
    for (py::handle item : nodes) {
      py::dict node = py::cast<py::dict>(py::reinterpret_borrow<py::object>(item));

      if (!node.contains("id"))
        throw std::runtime_error("build_tree_from_json: node missing 'id'");
      int id = py::cast<int>(node["id"]);

      bool isRoot = !node.contains("parent_id") || node["parent_id"].is_none();

      // Initial placement: explicit x/y if given, else a small deterministic
      // spread around the paper center so nodes are distinct and inside bounds.
      double x, y;
      if (node.contains("x") && node.contains("y") &&
          !node["x"].is_none() && !node["y"].is_none()) {
        x = py::cast<double>(node["x"]);
        y = py::cast<double>(node["y"]);
      } else {
        double r = 0.10 + 0.03 * double(order);
        double a = 2.39996 * double(order);            // golden-angle spread
        x = 0.5 * w + r * std::cos(a) * w;
        y = 0.5 * h + r * std::sin(a) * h;
        if (x < 0.0) x = 0.0; if (x > w) x = w;
        if (y < 0.0) y = 0.0; if (y > h) y = h;
      }

      tmNode* newNode = nullptr;
      tmEdge* newEdge = nullptr;

      if (isRoot) {
        mTree->AddNode(nullptr, tmPoint(x, y), newNode, newEdge);
      } else {
        int parentId = py::cast<int>(node["parent_id"]);
        auto it = mNodeMap.find(parentId);
        if (it == mNodeMap.end()) {
          std::ostringstream ss;
          ss << "build_tree_from_json: node " << id << " references unknown "
             << "parent_id " << parentId
             << " (parents must appear before their children)";
          throw std::runtime_error(ss.str());
        }
        mTree->AddNode(it->second, tmPoint(x, y), newNode, newEdge);

        // Set the proportional flap length on the edge just created.
        if (newEdge != nullptr && node.contains("length") &&
            !node["length"].is_none()) {
          double length = py::cast<double>(node["length"]);
          if (length > 0.0) newEdge->SetLength(length);
        }
        // Key the parent-edge by this (child) node's id, so the agent can
        // refer to "the edge above node N" as edge id N.
        if (newEdge != nullptr) mEdgeMap[id] = newEdge;
      }

      if (mNodeMap.count(id))
        throw std::runtime_error("build_tree_from_json: duplicate node id");
      mNodeMap[id] = newNode;
      ++order;
    }
  }

  /*
   * Pair two leaf nodes as mirror images about the paper's symmetry line
   * (TreeMaker condition NODES_SYMMETRIC / tmConditionNodesPaired). The paired
   * condition is a no-op unless the tree has a symmetry axis, so we establish
   * one (center of paper, 45-degree diagonal -- the classic origami axis and
   * the GUI default) the first time symmetry is requested.
   */
  void apply_symmetry(int node_a, int node_b) {
    auto ia = mNodeMap.find(node_a);
    auto ib = mNodeMap.find(node_b);
    if (ia == mNodeMap.end() || ib == mNodeMap.end())
      throw std::runtime_error("apply_symmetry: unknown node id");

    tmTreeCleaner tc(mTree);
    if (!mTree->HasSymmetry()) {
      mTree->SetHasSymmetry(true);
      mTree->SetSymmetry(
          tmPoint(0.5 * mTree->GetPaperWidth(), 0.5 * mTree->GetPaperHeight()),
          45.0);
    }
    // NODES_SYMMETRIC: enforce the two leaf nodes mirror across the axis.
    mTree->GetOrMakeTwoPartCondition<tmConditionNodesPaired, tmNode>(
        ia->second, ib->second);

    // Remember the pair so the post-optimization active-path projection can
    // keep them exact mirror images (otherwise it would drift the base
    // asymmetric while tightening the packing equalities).
    mSymPairs.emplace_back(ia->second, ib->second);
  }

  /*
   * Lock an edge's length (EDGE_LENGTH_FIXED / tmConditionEdgeLengthFixed) so
   * the strain optimizer cannot warp it. edge_id is the child node id whose
   * parent-edge should be fixed (see build_tree_from_json edge keying).
   */
  void set_edge_strain_fixed(int edge_id) {
    auto it = mEdgeMap.find(edge_id);
    if (it == mEdgeMap.end())
      throw std::runtime_error("set_edge_strain_fixed: unknown edge id (use the "
        "child node id of the edge to fix)");
    tmTreeCleaner tc(mTree);
    mTree->GetOrMakeOnePartCondition<tmConditionEdgeLengthFixed, tmEdge>(
        it->second);
  }

  /*
   * Run the ALM scale optimizer (circle packing). Returns the resulting design
   * scale. A very small value (< ~0.05) signals the flaps cannot be packed and
   * the agent should reduce edge lengths. Does NOT build geometry.
   */
  double run_scale_optimization() {
    if (mNodeMap.empty())
      throw std::runtime_error("no tree built; call build_tree_from_json first");

    tmNLCO* nlco = new tmNLCO_alm();
    tmScaleOptimizer* opt = new tmScaleOptimizer(mTree, nlco);
    try {
      opt->Initialize();
      opt->Optimize();
    } catch (const tmNLCO::EX_BAD_CONVERGENCE& ex) {
      delete opt; delete nlco;
      std::ostringstream ss;
      ss << "scale optimization did not converge (reason code "
         << ex.GetReason() << ")";
      throw std::runtime_error(ss.str());
    } catch (const tmScaleOptimizer::EX_BAD_SCALE&) {
      delete opt; delete nlco;
      throw std::runtime_error("scale optimization failed: scale collapsed too "
        "small (flaps cannot be packed onto this paper; reduce edge lengths)");
    } catch (...) {
      delete opt; delete nlco;
      throw std::runtime_error("scale optimization threw an unexpected error");
    }
    delete opt;        // optimizer does NOT own the NLCO
    delete nlco;
    return mTree->GetScale();
  }

  /*
   * GUI-style build: build the Universal Molecule directly from the current
   * (scale-optimized) base and export FOLD. This mirrors Action->Build Crease
   * Pattern in the TreeMaker GUI, which calls BuildPolysAndCreasePattern() with
   * NO strain optimization. Assumes run_scale_optimization() has already run.
   * Strain optimization is a separate, optional step (it relaxes edge lengths to
   * force a fit when scale-opt alone cannot pack) and perturbs an otherwise
   * clean uniaxial optimum, so it must NOT be on the default build path.
   */
  std::string build_and_export() {
    if (mNodeMap.empty())
      throw std::runtime_error("no tree built; call build_tree_from_json first");
    return BuildAndExport(mTree->GetScale());
  }

  // TEMP DIAGNOSTIC: after scale-opt, build the polygon network and dump the
  // per-leaf-path activity/border/feasibility flags so we can see exactly why
  // CalcPolygonValidity rejects a base. Returns a human-readable report.
  std::string debug_poly_report() {
    mTree->BuildTreePolys();
    std::ostringstream ss;
    ss << std::fixed << std::setprecision(5);
    ss << "scale=" << mTree->GetScale()
       << " IsPolygonValid=" << (mTree->IsPolygonValid() ? 1 : 0)
       << " nPolys=" << mTree->GetPolys().size() << "\n";
    tmArray<tmNode*> leaves;
    mTree->GetLeafNodes(leaves);
    ss << "leaf nodes (" << leaves.size() << "):\n";
    for (size_t i = 0; i < leaves.size(); ++i) {
      tmNode* n = leaves[i];
      ss << "  leaf#" << n->GetIndex() << " loc=(" << n->GetLoc().x << ","
         << n->GetLoc().y << ")\n";
    }
    tmArray<tmPath*> paths;
    mTree->GetLeafPaths(paths);
    ss << "leaf paths (" << paths.size() << "):\n";
    for (size_t i = 0; i < paths.size(); ++i) {
      tmPath* p = paths[i];
      const tmDpptrArray<tmNode>& pn = p->GetNodes();
      ss << "  " << pn.front()->GetIndex() << "->" << pn.back()->GetIndex()
         << " minPaper=" << p->GetMinPaperLength()
         << " actPaper=" << p->GetActPaperLength()
         << " A=" << (p->IsActivePath() ? 1 : 0)
         << " B=" << (p->IsBorderPath() ? 1 : 0)
         << " F=" << (p->IsFeasiblePath() ? 1 : 0)
         << " Poly=" << (p->IsPolygonPath() ? 1 : 0) << "\n";
    }
    return ss.str();
  }

  // TEMP DIAGNOSTIC: build the full crease pattern, then dump EVERY vertex with
  // its FOLD index, location, tree-node projection, border flag, incident-crease
  // count, and the Kind+Fold of each incident crease. The point is to locate the
  // odd-degree INTERIOR vertices (degree must be even for flat-foldability) and
  // see exactly which crease type (axial/gusset/ridge/hinge/pseudohinge) is
  // missing there. Kind letters: A=axial G=gusset R=ridge h=unfolded-hinge
  // H=folded-hinge P=pseudohinge. Fold letters: M/V/F/B (see FoldToAssignment).
  // (Temp; safe to remove once the molecule layer is solid.)
  std::string debug_vertex_report() {
    mTree->BuildTreePolys();
    if (!mTree->IsPolygonValid())
      return "polygon network not valid; cannot build crease pattern\n";
    mTree->BuildPolysAndCreasePattern();

    static const char* kindLetter[] = {"A", "G", "R", "h", "H", "P"};

    const tmDpptrArray<tmVertex>& verts = mTree->GetVertices();
    // Mirror ExportFold's index assignment so labels match the linted FOLD.
    std::map<const tmVertex*, std::size_t> vIndex;
    for (std::size_t i = 0; i < verts.size(); ++i) vIndex[verts[i]] = i;

    std::ostringstream ss;
    ss << std::fixed << std::setprecision(5);
    ss << "HasFullCP=" << (mTree->HasFullCP() ? 1 : 0)
       << " nVerts=" << verts.size()
       << " nCreases=" << mTree->GetCreases().size() << "\n";
    for (std::size_t i = 0; i < verts.size(); ++i) {
      const tmVertex* v = verts[i];
      const tmDpptrArray<tmCrease>& vc = v->GetCreases();
      bool border = v->IsBorderVertex();
      tmNode* tn = v->GetTreeNode();
      ss << "v" << i
         << (border ? " [border]" : " [INTERIOR]")
         << " loc=(" << v->GetLoc().x << "," << v->GetLoc().y << ")"
         << " node=" << (tn ? int(tn->GetIndex()) : -1)
         << " deg=" << vc.size();
      if (!border && (vc.size() % 2 != 0)) ss << " <<< ODD-DEGREE";
      ss << "  creases:";
      for (std::size_t j = 0; j < vc.size(); ++j) {
        const tmCrease* c = vc[j];
        int k = int(c->GetKind());
        const char* kl = (k >= 0 && k <= 5) ? kindLetter[k] : "?";
        ss << " " << kl << FoldToAssignment(c->GetFold());
      }
      ss << "\n";
    }
    return ss.str();
  }

  // TEMP DIAGNOSTIC: dump every crease with its kind, fold, and the color+order
  // of its two incident facets. A crease comes out FLAT iff its two facets share
  // a color; this report locates the facet-coloring inconsistency that turns
  // structural creases (e.g. ridges) flat. Color: U=up(color) W=white-up
  // N=not-oriented. (Temp; safe to remove once the molecule layer is solid.)
  std::string debug_crease_report() {
    mTree->BuildTreePolys();
    if (!mTree->IsPolygonValid())
      return "polygon network not valid; cannot build crease pattern\n";
    mTree->BuildPolysAndCreasePattern();

    static const char* kindLetter[] = {"AXIAL", "GUSSET", "RIDGE",
                                        "uHINGE", "fHINGE", "PSEUDO"};
    auto colLetter = [](const tmFacet* f) -> char {
      if (!f) return '-';
      switch (f->GetColor()) {
        case tmFacet::COLOR_UP:    return 'U';
        case tmFacet::WHITE_UP:    return 'W';
        default:                   return 'N';
      }
    };
    const tmDpptrArray<tmVertex>& verts = mTree->GetVertices();
    std::map<const tmVertex*, std::size_t> vIndex;
    for (std::size_t i = 0; i < verts.size(); ++i) vIndex[verts[i]] = i;

    const tmDpptrArray<tmCrease>& creases = mTree->GetCreases();
    std::ostringstream ss;
    ss << "nCreases=" << creases.size()
       << " nFacets=" << mTree->GetFacets().size() << "\n";
    for (std::size_t i = 0; i < creases.size(); ++i) {
      const tmCrease* c = creases[i];
      const tmDpptrArray<tmVertex>& cv = c->GetVertices();
      int a = (cv.size() >= 1 && vIndex.count(cv[0])) ? int(vIndex[cv[0]]) : -1;
      int b = (cv.size() >= 2 && vIndex.count(cv[1])) ? int(vIndex[cv[1]]) : -1;
      const tmFacet* ff = c->GetFwdFacet();
      const tmFacet* bf = c->GetBkdFacet();
      int k = int(c->GetKind());
      ss << "c" << i << " " << ((k >= 0 && k <= 5) ? kindLetter[k] : "?")
         << " fold=" << FoldToAssignment(c->GetFold())
         << " v" << a << "-v" << b
         << "  fwd[col=" << colLetter(ff)
         << ",ord=" << (ff ? int(ff->GetOrder()) : -1)
         << ",src=" << (ff && ff->IsSourceFacet() ? 1 : 0) << "]"
         << "  bkd[col=" << colLetter(bf)
         << ",ord=" << (bf ? int(bf->GetOrder()) : -1)
         << ",src=" << (bf && bf->IsSourceFacet() ? 1 : 0) << "]";
      if (ff && bf && ff->GetColor() == bf->GetColor() && c->GetKind() != tmCrease::UNFOLDED_HINGE)
        ss << "  <<< SAME-COLOR (should fold!)";
      ss << "\n";
    }
    return ss.str();
  }

  /*
   * Run the ALM strain optimizer over all nodes/edges (conditions such as
   * EDGE_LENGTH_FIXED and NODES_SYMMETRIC constrain the result), then build the
   * Universal Molecule and return the .fold JSON string. Assumes scale
   * optimization has already run. Throws std::runtime_error on any failure.
   */
  std::string run_strain_optimization_and_export() {
    if (mNodeMap.empty())
      throw std::runtime_error("no tree built; call build_tree_from_json first");

    // ---- 1. Strain optimization (ALM backend) ----
    // Pattern from tmModelTester.cpp:DoStrainOptimization. We pass copies of
    // all owned nodes/edges; conditions added above supply the constraints that
    // pin nodes or fix edge lengths.
    tmNLCO* nlco = new tmNLCO_alm();
    tmStrainOptimizer* opt = new tmStrainOptimizer(mTree, nlco);
    tmDpptrArray<tmNode> movingNodes = mTree->GetOwnedNodes();
    tmDpptrArray<tmEdge> stretchyEdges = mTree->GetOwnedEdges();
    try {
      opt->Initialize(movingNodes, stretchyEdges);
      opt->Optimize();
    } catch (const tmStrainOptimizer::EX_NO_MOVING_NODES_OR_EDGES&) {
      delete opt; delete nlco;
      throw std::runtime_error("strain optimization has no movable nodes/edges "
        "(every part is fixed or pinned)");
    } catch (const tmNLCO::EX_BAD_CONVERGENCE& ex) {
      delete opt; delete nlco;
      std::ostringstream ss;
      ss << "strain optimization did not converge (reason code "
         << ex.GetReason() << ")";
      throw std::runtime_error(ss.str());
    } catch (...) {
      delete opt; delete nlco;
      throw std::runtime_error("strain optimization threw an unexpected error");
    }
    delete opt;        // optimizer does NOT own the NLCO
    delete nlco;

    return BuildAndExport(mTree->GetScale());
  }

  /*
   * Golden Base pipeline. Load a fully-solved tree from a TreeMaker file
   * (.tmd/.tmd5) that was saved by the GUI AFTER "Build Crease Pattern", and
   * export its crease pattern as a .fold JSON string. NO optimization is run:
   * the file already contains converged vertices and creases.
   *
   * GetSelf() is TreeMaker's native v3/v4/v5 deserializer (NOT XML, despite the
   * .tmd5 name -- it's a token stream). Only the v5 format carries the crease
   * pattern; v4 export strips polys/vertices/creases, so re-save as native v5.
   */
  std::string load_and_export_tmd(const std::string& filepath) {
    std::ifstream fin(filepath.c_str());
    if (!fin.good())
      throw std::runtime_error(
          "load_and_export_tmd: cannot open file '" + filepath + "'");

    // Start from a clean tree.
    delete mTree;
    mTree = new tmTree();
    mNodeMap.clear();
    mEdgeMap.clear();
    mSymPairs.clear();

    try {
      mTree->GetSelf(fin);
    } catch (const tmTree::EX_IO_UNRECOGNIZED_CONDITION& e) {
      throw std::runtime_error(
          "load_and_export_tmd: file contains " +
          std::to_string(e.mNumMissed) + " unrecognized condition(s)");
    } catch (const tmPart::EX_IO_BAD_TOKEN& e) {
      throw std::runtime_error(
          "load_and_export_tmd: malformed file (bad tag/version/token near \"" +
          e.mToken + "\")");
    } catch (...) {
      throw std::runtime_error(
          "load_and_export_tmd: failed to parse '" + filepath + "'");
    }

    // A Golden Base must already carry geometry; if not, tell the human how to
    // produce one rather than returning an empty FOLD.
    if (mTree->GetVertices().size() == 0 || mTree->GetCreases().size() == 0) {
      std::ostringstream ss;
      ss << "loaded tree has no crease pattern (vertices="
         << mTree->GetVertices().size() << ", creases="
         << mTree->GetCreases().size()
         << "). In the TreeMaker GUI, run Action->Build Crease Pattern and save "
         << "in native (v5) format before converting.";
      throw std::runtime_error(ss.str());
    }

    return ExportFold(mTree->GetScale());
  }

public:
  // Diagnostic: after scale-opt, build the polygon network, measure the largest
  // active-path length residual, project, and measure it again. Returns a short
  // "before -> after (nIters, nCons)" line. Proves the precision gain that fixes
  // the v5-class interior-vertex Kawasaki violation without touching the molecule
  // build. (Temp; safe to remove once the projection is trusted.)
  std::string debug_active_path_report() {
    mTree->BuildTreePolys();
    if (!mTree->IsPolygonValid())
      return "polygon network not valid; cannot report active paths\n";
    double before = MaxActivePathResidual();
    std::size_t iters = 0, cons = 0;
    ProjectActivePaths(&iters, &cons);
    mTree->BuildTreePolys();
    double after = MaxActivePathResidual();
    std::ostringstream ss;
    ss << std::scientific << std::setprecision(3)
       << "active-path |residual|: " << before << " -> " << after
       << "  (" << iters << " GN iters, " << cons << " constraints)\n";
    return ss.str();
  }

private:
  // Largest |actPaperLength - minPaperLength| over the active axis-parallel leaf
  // paths -- the binding circle/river-packing equalities. Requires a current
  // polygon network (call BuildTreePolys first).
  double MaxActivePathResidual() {
    tmArray<tmPath*> paths;
    mTree->GetLeafPaths(paths);
    double maxr = 0.0;
    for (std::size_t k = 0; k < paths.size(); ++k) {
      tmPath* p = paths[k];
      if (!(p->IsActivePath() && p->IsAxisParallelPath())) continue;
      double res = std::fabs(double(p->GetActPaperLength()) -
                             double(p->GetMinPaperLength()));
      maxr = std::max(maxr, res);
    }
    return maxr;
  }

  /*
   * Post-optimization precision polish: project the leaf-node positions onto the
   * active-path constraint manifold, holding the design scale fixed.
   *
   * The ALM scale optimizer converges the binding circle/river-packing equalities
   * (|loc_a - loc_b| == scale * treeLen) only to its penalty-feasibility floor
   * (~1e-5..1e-6, set by WEIGHT_MAX). That residual survives into the Universal
   * Molecule as a ~1e-6 deg Kawasaki error at interior vertices, which Oriedita's
   * ~1e-6 deg tolerance then rejects (the "v5" quad blocker). Raising the global
   * penalty fixes the quad but flips a star hinge FLAT -- no single global weight
   * serves both grid and non-grid bases. So we tighten LOCALLY instead.
   *
   * Each active leaf path contributes one equality residual
   *     r_k = |loc(front_k) - loc(back_k)| - scale*treeLen_k = 0,
   * whose only free variables are the two leaf endpoints' (x,y) (a branch node on
   * the path lies on the chord but does not enter its length). We Gauss-Newton on
   * r holding the active set and scale fixed: d|a-b|/da = (a-b)/|a-b| = u, so the
   * Jacobian row is +u at a, -u at b. The normal system (J^T J + lambda I) dX =
   * -J^T r is tiny (2*leafCount unknowns); lambda damps the translation/rotation
   * gauge null space. A handful of iterations drive the residual to ~1e-13, so the
   * molecule's interior angles come out exact. This is the irrational-coordinate
   * analogue of "snap the star to its grid" (which made Oriedita Pass).
   */
  void ProjectActivePaths(std::size_t* outIters = nullptr,
                          std::size_t* outCons = nullptr) {
    if (outIters) *outIters = 0;
    if (outCons)  *outCons  = 0;

    // Free variables = leaf-node coordinates.
    tmArray<tmNode*> leaves;
    mTree->GetLeafNodes(leaves);
    const std::size_t L = leaves.size();
    if (L == 0) return;
    std::map<tmNode*, std::size_t> idx;
    for (std::size_t i = 0; i < L; ++i) idx[leaves[i]] = i;
    std::vector<double> x(L), y(L);
    for (std::size_t i = 0; i < L; ++i) {
      x[i] = double(leaves[i]->GetLocX());
      y[i] = double(leaves[i]->GetLocY());
    }

    // Active axis-parallel leaf-path equalities. minPaperLength = scale*treeLen
    // is fixed (scale and tree edges are held), so capture it once.
    struct Con { std::size_t a, b; double target; };
    std::vector<Con> cons;
    tmArray<tmPath*> paths;
    mTree->GetLeafPaths(paths);
    for (std::size_t k = 0; k < paths.size(); ++k) {
      tmPath* p = paths[k];
      if (!(p->IsActivePath() && p->IsAxisParallelPath())) continue;
      const tmDpptrArray<tmNode>& pn = p->GetNodes();
      if (pn.size() < 2) continue;
      auto ia = idx.find(pn.front());
      auto ib = idx.find(pn.back());
      if (ia == idx.end() || ib == idx.end()) continue;   // endpoint not a leaf
      cons.push_back({ia->second, ib->second,
                      double(p->GetMinPaperLength())});
    }
    if (cons.empty()) return;

    // Symmetry rows: each mirror-paired leaf pair (a,b) about the 45-degree axis
    // y=x through the paper center (0.5,0.5) must satisfy b=(a.y,a.x), i.e. the
    // two linear equalities b.x - a.y = 0 and b.y - a.x = 0. Carrying these in
    // the same least-squares system keeps the base symmetric while the active
    // paths tighten (free projection would drift it asymmetric).
    struct SymCon { std::size_t a, b; };
    std::vector<SymCon> syms;
    for (const auto& pr : mSymPairs) {
      auto ia = idx.find(pr.first);
      auto ib = idx.find(pr.second);
      if (ia == idx.end() || ib == idx.end()) continue;   // not both leaves
      syms.push_back({ia->second, ib->second});
    }
    if (outCons) *outCons = cons.size() + 2 * syms.size();

    const std::size_t n = 2 * L;
    const double w = double(mTree->GetPaperWidth());
    const double h = double(mTree->GetPaperHeight());
    const double lambda = 1e-9;   // damps the translation/rotation gauge
    const double tol = 1e-13;
    const std::size_t maxIters = 50;

    std::size_t it = 0;
    for (; it < maxIters; ++it) {
      std::vector<double> A(n * n, 0.0), g(n, 0.0);
      double maxr = 0.0;
      for (std::size_t c = 0; c < cons.size(); ++c) {
        const std::size_t a = cons[c].a, b = cons[c].b;
        const double dx = x[a] - x[b], dy = y[a] - y[b];
        const double dist = std::sqrt(dx * dx + dy * dy);
        if (dist < 1e-15) continue;             // coincident; skip (degenerate)
        const double res = dist - cons[c].target;
        maxr = std::max(maxr, std::fabs(res));
        const double ux = dx / dist, uy = dy / dist;
        const std::size_t cols[4] = {2 * a, 2 * a + 1, 2 * b, 2 * b + 1};
        const double Jrow[4] = {ux, uy, -ux, -uy};
        for (int i = 0; i < 4; ++i) {
          g[cols[i]] += Jrow[i] * res;          // J^T r
          for (int j = 0; j < 4; ++j)
            A[cols[i] * n + cols[j]] += Jrow[i] * Jrow[j];   // J^T J
        }
      }
      // Symmetry equalities (linear; two rows per pair). Row 1: x[b]-y[a]=0
      // (cols 2b:+1, 2a+1:-1). Row 2: y[b]-x[a]=0 (cols 2b+1:+1, 2a:-1).
      for (std::size_t s = 0; s < syms.size(); ++s) {
        const std::size_t a = syms[s].a, b = syms[s].b;
        const std::size_t row1[2] = {2 * b, 2 * a + 1};
        const double      c1[2]   = {1.0, -1.0};
        const double      r1      = x[b] - y[a];
        const std::size_t row2[2] = {2 * b + 1, 2 * a};
        const double      c2[2]   = {1.0, -1.0};
        const double      r2      = y[b] - x[a];
        maxr = std::max(maxr, std::max(std::fabs(r1), std::fabs(r2)));
        for (int i = 0; i < 2; ++i) {
          g[row1[i]] += c1[i] * r1;
          g[row2[i]] += c2[i] * r2;
          for (int j = 0; j < 2; ++j) {
            A[row1[i] * n + row1[j]] += c1[i] * c1[j];
            A[row2[i] * n + row2[j]] += c2[i] * c2[j];
          }
        }
      }
      if (maxr < tol) break;
      for (std::size_t d = 0; d < n; ++d) A[d * n + d] += lambda;
      // Solve (J^T J + lambda I) dX = -J^T r.
      for (std::size_t d = 0; d < n; ++d) g[d] = -g[d];
      std::vector<double> dX;
      if (!SolveDense(A, g, n, dX)) break;       // singular; keep best so far
      for (std::size_t i = 0; i < L; ++i) {
        x[i] += dX[2 * i];
        y[i] += dX[2 * i + 1];
        if (x[i] < 0.0) x[i] = 0.0; if (x[i] > w) x[i] = w;   // stay on paper
        if (y[i] < 0.0) y[i] = 0.0; if (y[i] > h) y[i] = h;
      }
    }
    if (outIters) *outIters = it;

    // Write refined coordinates back. One outer cleaner so the (deferred)
    // CleanupAfterEdit recomputes path lengths / active flags / polys once.
    tmTreeCleaner tc(mTree);
    for (std::size_t i = 0; i < L; ++i)
      leaves[i]->SetLoc(tmPoint(x[i], y[i]));
  }

  // Build the polygon network + Universal Molecule from the current base (at the
  // given scale) and return the FOLD string. Shared by the scale-only and
  // strain paths. Steps mirror the GUI's Build Crease Pattern.
  std::string BuildAndExport(double scale) {
    // ---- Polygon network (safe) -> validity gate ----
    // BuildTreePolys() builds polygon outlines without filling them, so it is
    // safe to call and lets us reject invalid networks with a clean error
    // BEFORE the fragile molecule/facet build (which can hard-crash the legacy
    // engine on a not-fully-converged base rather than failing gracefully).
    mTree->BuildTreePolys();
    if (!mTree->IsPolygonValid()) {
      std::ostringstream ss;
      ss << "polygon network is not valid after optimization (scale="
         << scale << "): the active-path network does not form a valid polygon "
         << "partition, so the Universal Molecule cannot be built. The base is "
         << "not at a complete uniaxial optimum -- it likely needs additional "
         << "active-path/angle conditions or a different proportion/symmetry.";
      throw std::runtime_error(ss.str());
    }

    // ---- Precision polish: project leaf coords onto the active-path manifold ----
    // Tightens the binding equalities from the ALM penalty floor (~1e-6) to
    // ~1e-13 so interior-vertex Kawasaki angles come out exact. Holds scale and
    // the active set fixed, so it does not change discrete topology; the move is
    // ~1e-5, well inside the active basin. SetLoc scheduled a CleanupAfterEdit;
    // rebuild polys on the refined coords before the molecule build.
    ProjectActivePaths();
    mTree->BuildTreePolys();
    if (!mTree->IsPolygonValid()) {
      std::ostringstream ss;
      ss << "polygon network became invalid after active-path projection "
         << "(scale=" << scale << "); this should not happen for a converged "
         << "base -- report it.";
      throw std::runtime_error(ss.str());
    }

    // ---- Universal Molecule -> crease pattern ----
    // NOTE: on a polygon-valid-but-not-fully-converged base the legacy facet
    // builder can segfault. server.py runs this in an isolated child process so
    // such a crash is reported as an error instead of taking down the server.
    mTree->BuildPolysAndCreasePattern();
    if (!mTree->HasFullCP()) {
      tmArray<tmEdge*>   badEdges;
      tmArray<tmPoly*>   badPolys;
      tmArray<tmVertex*> badVertices;
      tmArray<tmCrease*> badCreases;
      tmArray<tmFacet*>  badFacets;
      tmTree::CPStatus status = mTree->GetCPStatus(
          badEdges, badPolys, badVertices, badCreases, badFacets);
      std::ostringstream ss;
      ss << "could not build a full crease pattern (scale=" << scale << "): "
         << CPStatusToString(status);
      throw std::runtime_error(ss.str());
    }

    // ---- Emit FOLD JSON ----
    return ExportFold(scale);
  }

  // Build a FOLD-format JSON string from the tree's vertices and creases.
  std::string ExportFold(double scale) {
    const tmDpptrArray<tmVertex>& verts = mTree->GetVertices();
    const tmDpptrArray<tmCrease>& creases = mTree->GetCreases();

    // Map each tmVertex* to its 0-based position in vertices_coords. We build
    // our own map rather than trust tmPart::GetIndex() (which is a tree-global
    // 1-based id, not a position in this array).
    std::map<const tmVertex*, std::size_t> vIndex;
    std::ostringstream coords;
    coords << std::fixed << std::setprecision(9);
    coords << "[";
    for (std::size_t i = 0; i < verts.size(); ++i) {
      const tmVertex* v = verts[i];
      vIndex[v] = i;
      const tmPoint& p = v->GetLoc();
      if (i) coords << ",";
      coords << "[" << p.x << "," << p.y << "]";
    }
    coords << "]";

    std::ostringstream ev, ea;
    ev << "[";
    ea << "[";
    bool first = true;
    for (std::size_t i = 0; i < creases.size(); ++i) {
      const tmCrease* c = creases[i];
      const tmDpptrArray<tmVertex>& cv = c->GetVertices();
      if (cv.size() < 2) continue;          // a crease has exactly two ends
      auto a = vIndex.find(cv[0]);
      auto b = vIndex.find(cv[1]);
      if (a == vIndex.end() || b == vIndex.end()) continue;
      if (!first) { ev << ","; ea << ","; }
      first = false;
      ev << "[" << a->second << "," << b->second << "]";
      ea << "\"" << FoldToAssignment(c->GetFold()) << "\"";
    }
    ev << "]";
    ea << "]";

    std::ostringstream fold;
    fold << std::fixed << std::setprecision(6);
    fold << "{"
         << "\"file_spec\":1.1,"
         << "\"file_creator\":\"headless_treemaker\","
         << "\"file_classes\":[\"singleModel\"],"
         << "\"frame_title\":\"TreeMaker crease pattern (scale="
                << scale << ")\","
         << "\"frame_classes\":[\"creasePattern\"],"
         << "\"frame_attributes\":[\"2D\"],"
         << "\"vertices_coords\":" << coords.str() << ","
         << "\"edges_vertices\":" << ev.str() << ","
         << "\"edges_assignment\":" << ea.str()
         << "}";
    return fold.str();
  }

  tmTree* mTree;
  std::map<int, tmNode*> mNodeMap;   // JSON node id -> tmNode*
  std::map<int, tmEdge*> mEdgeMap;   // child node id -> its parent tmEdge*
  std::vector<std::pair<tmNode*, tmNode*>> mSymPairs;  // mirror-paired leaf nodes
};

PYBIND11_MODULE(headless_treemaker, m) {
  m.doc() = "Headless TreeMaker math engine (thin vertical slice)";

  // REQUIRED once per process before any tree I/O or construction: populates
  // TreeMaker's dynamic part/tag registry. Without it, all tree operations fail.
  tmPart::InitTypes();

  py::class_<HeadlessTreemaker>(m, "HeadlessTreemaker")
      .def(py::init<>())
      .def("init_paper", &HeadlessTreemaker::init_paper,
           py::arg("width"), py::arg("height"))
      .def("build_tree_from_json", &HeadlessTreemaker::build_tree_from_json,
           py::arg("tree_json_string"))
      .def("apply_symmetry", &HeadlessTreemaker::apply_symmetry,
           py::arg("node_a"), py::arg("node_b"))
      .def("set_edge_strain_fixed", &HeadlessTreemaker::set_edge_strain_fixed,
           py::arg("edge_id"))
      .def("run_scale_optimization",
           &HeadlessTreemaker::run_scale_optimization)
      .def("build_and_export",
           &HeadlessTreemaker::build_and_export)
      .def("debug_poly_report",
           &HeadlessTreemaker::debug_poly_report)
      .def("debug_vertex_report",
           &HeadlessTreemaker::debug_vertex_report)
      .def("debug_crease_report",
           &HeadlessTreemaker::debug_crease_report)
      .def("debug_active_path_report",
           &HeadlessTreemaker::debug_active_path_report)
      .def("run_strain_optimization_and_export",
           &HeadlessTreemaker::run_strain_optimization_and_export)
      .def("load_and_export_tmd", &HeadlessTreemaker::load_and_export_tmd,
           py::arg("filepath"));
}
