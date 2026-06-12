# TreeMaker engine fork — history archive

`treemaker-fork.bundle` is a complete git archive of the local `treemaker/` fork
(a clone of [vishvish/treemaker](https://github.com/vishvish/treemaker)) that
used to live at the project root. It was bundled and removed once the monorepo
absorbed everything under `origami-design-ide`, since the build only ever used
the **vendored** engine subset at `mcp_harness/treemaker/`.

## Why keep it

The fork's `origin` was `vishvish/treemaker` (not ours), so these headless fix
commits were never pushed anywhere we control. The *code* survives in the
vendored copy; this bundle preserves the *commit history / provenance*:

- `fb5cc4b` fix(headless): tighten ALM convergence tolerances 1e-5 -> 1e-8
- `2720fdd` fix(headless): repair off-by-one in tmArray MoveItem/NthItem (regression #8)
- `5419c6f` fix(headless): repair d737e92 molecule-builder regressions #1-7 + crash hardening

(branch `headless-engine-fixes` and `main` both point at `fb5cc4b`.)

## Restore

```bash
# Clone the whole fork back out of the bundle:
git clone docs/engine-history/treemaker-fork.bundle treemaker-restored

# Or inspect a single fix without cloning:
git bundle verify docs/engine-history/treemaker-fork.bundle
```
