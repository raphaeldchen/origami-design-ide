#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Build the headless_treemaker Pybind11 extension WITHOUT cmake, using clang++
# directly (equivalent to CMakeLists.txt). Works on macOS / Command Line Tools.
#
#   ./build.sh            # builds headless_treemaker.<ext>.so in this dir
#
# Requires: clang++, python3 with dev headers, pybind11 (pip install pybind11).
# ---------------------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TM_SRC="${HERE}/../treemaker/Source"
TM_MODEL="${TM_SRC}/tmModel"

# Interpreter to build against (override with PYTHON=/path/to/python ./build.sh).
PYTHON="${PYTHON:-python3}"

# Python / pybind11 include flags and the platform extension suffix.
PYINCLUDES="$("${PYTHON}" -m pybind11 --includes)"
EXT_SUFFIX="$("${PYTHON}" -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')"
OUT="${HERE}/headless_treemaker${EXT_SUFFIX}"

INCS=(
  -I"${TM_SRC}" -I"${TM_MODEL}"
  -I"${TM_MODEL}/tmNLCO" -I"${TM_MODEL}/tmSolvers" -I"${TM_MODEL}/tmOptimizers"
  -I"${TM_MODEL}/tmTreeClasses" -I"${TM_MODEL}/tmPtrClasses"
  -I"${TM_MODEL}/wnlib" -I"${TM_MODEL}/wnlib/cmp" -I"${TM_MODEL}/wnlib/conjdir"
  -I"${TM_MODEL}/wnlib/cpy" -I"${TM_MODEL}/wnlib/list" -I"${TM_MODEL}/wnlib/low"
  -I"${TM_MODEL}/wnlib/mat" -I"${TM_MODEL}/wnlib/mem" -I"${TM_MODEL}/wnlib/random"
  -I"${TM_MODEL}/wnlib/vect"
)

# tmModel sources, excluding the wnlib subtree (alternate optimizer backend).
MODEL_SOURCES=()
while IFS= read -r f; do MODEL_SOURCES+=("$f"); done < <(find "${TM_MODEL}" -name '*.cpp' -not -path '*/wnlib/*')

echo "==> Compiling headless_treemaker (${#MODEL_SOURCES[@]} model sources)..."
clang++ ${TM_OPT:--O2} -std=c++20 -DNDEBUG -fPIC -fvisibility=hidden \
  -shared -undefined dynamic_lookup \
  ${PYINCLUDES} "${INCS[@]}" \
  "${HERE}/TreemakerWrapper.cpp" \
  "${MODEL_SOURCES[@]}" \
  "${TM_SRC}/tmHeader.cpp" "${TM_SRC}/tmPrec.cpp" \
  -o "${OUT}"

echo "==> Built: ${OUT}"
