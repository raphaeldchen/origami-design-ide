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

private:
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
      .def("run_strain_optimization_and_export",
           &HeadlessTreemaker::run_strain_optimization_and_export)
      .def("load_and_export_tmd", &HeadlessTreemaker::load_and_export_tmd,
           py::arg("filepath"));
}
