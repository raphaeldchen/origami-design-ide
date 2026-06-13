# Vendored TreeMaker engine source

This `treemaker/Source/` tree is a **vendored, minimal subset** of Robert J.
Lang's TreeMaker, included so `origami-design-ide` rebuilds the headless
`headless_treemaker.so` from a fresh clone with no external checkout.

## Provenance
- Upstream: `github.com/vishvish/treemaker`, branch `main` @ `b100fe0`
  ("fix: add LICENCE to DMGs and update README").
- On top of upstream, three headless-engine fix commits (see their messages in
  the original clone, summarized in `../HANDOFF_molecule_topology.md`):
  - `5419c6f` — d737e92 molecule-builder regressions #1–7 + crash/hang hardening.
  - `2720fdd` — tmArray `MoveItem`/`NthItem` off-by-one (#8, the caterpillar SIGSEGV).
  - `fb5cc4b` — ALM convergence tolerance 1e-5 → 1e-8 (flat-foldability precision).

## Scope
Only the headless-buildable subset is vendored: `Source/tmModel/**` (the model
engine, incl. the `wnlib` headers) plus the loose `Source/` files `tmHeader.{cpp,h}`,
`tmPrec.cpp`, `tmTree.h`, `tmVersion.h`. The GUI (`tmwxGUI`, `images`, `help`,
`about`, `test`) is intentionally excluded — `build.sh` never compiles it.

## IMPORTANT: this is now the source of truth
`build.sh` compiles from THIS tree (`${HERE}/treemaker/Source`). Any further
engine edits must be made here to take effect — the external `vishvish/treemaker`
clone is no longer on the build path.
