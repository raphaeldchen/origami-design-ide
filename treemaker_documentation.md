# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build Commands

Prerequisites: macOS 13.3+, Xcode Command Line Tools, CMake 3.15+.

```sh
# Debug build (default) — downloads and compiles wxWidgets 3.2.7 on first run
./treemaker/build.sh

# Release build
./treemaker/build.sh Release

# Clean TreeMaker build artifacts (keeps wxWidgets in deps/)
./treemaker/build.sh clean

# Clean everything including wxWidgets
./treemaker/build.sh clean-all
```

Built app: `treemaker/build/bin/TreeMaker.app`  
Run: `open treemaker/build/bin/TreeMaker.app`  
Debug: `lldb treemaker/build/bin/TreeMaker.app/Contents/MacOS/TreeMaker`

### Tests

Tests are disabled by default. Enable with:

```sh
cd treemaker/build
cmake .. -DBUILD_TESTING=ON
cmake --build . -j$(sysctl -n hw.ncpu)
```

Test binaries (no GUI, no `TMWX`): `tmArrayTester`, `tmDpptrTester`, `tmNewtonRaphsonTester`, `tmNLCOTester`, `tmModelTester`.

## Architecture Overview

The codebase has two independent layers:

**`Source/tmModel`** — the pure mathematical model, no wxWidgets dependency.  
**`Source/tmwxGUI`** — the wxWidgets GUI layer that wraps the model.

`tmHeader.h` is the required prefix header for all code. `TMWX` must be defined for any GUI compilation unit; test code must not define it.

### Model Layer (`Source/tmModel`)

`tmTree` is the central class and owns all parts via `tmDpptrArray<T>` (dangle-proof owning arrays). Parts cross-reference each other through `tmDpptr<T>` pointers, which automatically null themselves when the target is destroyed.

**Part hierarchy:**
- `tmNode` — nodes in the stick figure (leaf nodes map to flaps)
- `tmEdge` — edges of the stick figure (tree edges with lengths)
- `tmPath` — paths between node pairs (the distance constraints)
- `tmPoly` — convex polygons in the crease pattern
- `tmVertex` / `tmCrease` / `tmFacet` — crease pattern elements

**Conditions** are polymorphic constraints stored in `tmTree::mConditions`. The 14 concrete types (e.g., `tmConditionNodeFixed`, `tmConditionPathAngleQuant`) are created exclusively through `tmTree::MakeOnePartCondition<C,P>()` template methods.

**`tmTreeCleaner`** is a critical RAII guard: constructing it marks the tree dirty, and its destructor calls `tmTree::CleanupAfterEdit()`, which recomputes all derived state (path feasibility, polygon network, crease pattern, facet order). Any method that mutates the tree must hold a `tmTreeCleaner` on the stack.

**Subdirectories:**
- `tmTreeClasses` — all `tmPart` subclasses and condition types
- `tmNLCO` — nonlinear constrained optimization interface
- `tmOptimizers` — `tmScaleOptimizer`, `tmStrainOptimizer`, `tmEdgeOptimizer`, `tmStubFinder`
- `tmSolvers` — Newton-Raphson root-finding
- `tmPtrClasses` — `tmArray`, `tmDpptr`, `tmDpptrArray`, `tmArrayIterator`
- `wnlib` — third-party C numerical library (conjugate-direction optimizer); known warnings are pre-existing

### GUI Layer (`Source/tmwxGUI`)

Uses the wxWidgets document/view architecture:

- `tmwxDoc` — the wxDocument; owns the `tmTree`; split across `tmwxDoc_Action.cpp`, `tmwxDoc_Condition.cpp`, `tmwxDoc_Edit.cpp`, `tmwxDoc_File.cpp`, `tmwxDoc_View.cpp`, `tmwxDoc_Debug.cpp`
- `tmwxView` / `tmwxDesignFrame` / `tmwxDesignCanvas` — view and canvas for interactive editing
- `tmwxInspector` — per-condition inspector panels (one `.cpp`/`.h` pair per condition type)
- `tmwxPalette` — floating tool palettes
- `tmwxFoldedForm` — folded-form 3D visualization
- `tmwxOptimizerDialog` — optimizer parameter dialogs
- `tmwxCommon` — shared utility widgets and helpers

## Code Conventions

Class name prefixes:
- `tm` — model classes (`tmNode`, `tmTree`, `tmEdge`)
- `tmwx` — GUI classes wrapping wxWidgets (`tmwxDoc`, `tmwxDesignCanvas`)
- `wx` — wxWidgets library classes (untouched)

Naming:
- Classes and functions: `PascalCase`
- Variables: `camelCase`
- Member variables: `m` prefix (`mLoc`, `mPath`)
- Static members: `s` prefix (`sTag`)
- Macros, constants, enum values: `ALL_CAPS`

Large implementation files may be split by concern using a `_Usage` suffix (e.g., `tmwxDoc_Action.cpp`).

## Preprocessor Symbols

| Symbol | Meaning |
|--------|---------|
| `TMWX` | Building the full GUI app (required for all wxWidgets code) |
| `TMDEBUG` | Enables `TMASSERT` checks (dialog on failure, then terminate) |
| `__WXDEBUG__` | wxWidgets debug mode (assertions break into debugger) |
| `TMPROFILE` | Timing/profiling output to log |

Build configurations: **Debug** (`__WXDEBUG__` + `TMDEBUG` + `TMWX`), **Development** (`TMDEBUG` + `TMWX`), **Profile** (`TMPROFILE` + `TMWX`), **Release** (`TMWX` only).

## Known Issues

`wnlib` (third-party C library) has pre-existing compiler warnings (unsafe sprintf, format string mismatches, deprecated `register`, string literal conversions). These are tracked in `treemaker/updates.md` and do not affect correctness on modern 64-bit builds.
