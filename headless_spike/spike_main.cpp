/*
 * Feasibility spike (throwaway): prove the TreeMaker math core runs headless.
 *
 * Loads a .tmd5 tree, runs an ALM scale optimization, prints the result.
 * Mirrors the pattern in Source/test/tmModelTester/tmModelTester.cpp
 * (DoScaleOptimization), but with zero GUI / wxWidgets.
 *
 * Usage: spike_main <path-to.tmd5>
 */
#include <iostream>
#include <fstream>
#include <string>

#include "tmModel.h"      // umbrella: tmTree, optimizers, tmNLCO, ...
#include "tmNLCO_alm.h"   // the freely-distributable optimizer backend

int main(int argc, char** argv)
{
  if (argc < 2) {
    std::cerr << "usage: " << argv[0] << " <path-to.tmd5>\n";
    return 2;
  }
  const std::string path = argv[1];

  // REQUIRED once before any tree I/O: builds the dynamic tag/type registry.
  // (The GUI app and tmModelTester both call this at startup.)
  tmPart::InitTypes();

  tmTree* tree = new tmTree();
  {
    std::ifstream fin(path.c_str());
    if (!fin.good()) {
      std::cerr << "cannot open " << path << "\n";
      return 2;
    }
    try {
      tree->GetSelf(fin);
    } catch (const tmTree::EX_IO_UNRECOGNIZED_CONDITION& e) {
      std::cerr << "parse: " << e.mNumMissed << " unrecognized condition(s)\n";
      return 1;
    } catch (const tmPart::EX_IO_BAD_TOKEN& e) {
      std::cerr << "parse: bad token / tag / version: \"" << e.mToken << "\"\n";
      return 1;
    } catch (...) {
      std::cerr << "failed to parse tree from " << path << " (unknown exception)\n";
      return 1;
    }
  }

  std::cout << "Loaded tree: "
            << tree->GetNodes().size() << " nodes, "
            << tree->GetEdges().size() << " edges. "
            << "Paper " << tree->GetPaperWidth() << " x "
            << tree->GetPaperHeight() << ", "
            << "initial scale " << tree->GetScale() << "\n";

  tmNLCO* nlco = new tmNLCO_alm();
  tmScaleOptimizer* opt = new tmScaleOptimizer(tree, nlco);
  opt->Initialize();

  int rc = 0;
  try {
    opt->Optimize();
    std::cout << "ALM scale optimization SUCCEEDED. New scale = "
              << tree->GetScale() << "\n";
  } catch (const tmNLCO::EX_BAD_CONVERGENCE& ex) {
    std::cout << "Optimizer ran but did not converge (rc="
              << ex.GetReason() << ")\n";
    rc = 1;
  } catch (const tmScaleOptimizer::EX_BAD_SCALE&) {
    std::cout << "Optimizer ran; scale collapsed too small.\n";
    rc = 1;
  } catch (...) {
    std::cout << "Optimizer threw an unexpected exception.\n";
    rc = 1;
  }

  delete opt;   // optimizer does NOT own the NLCO (per tmModelTester)
  delete nlco;
  delete tree;
  return rc;
}
