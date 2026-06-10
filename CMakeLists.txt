# ---------------------------------------------------------------------------
# CMake build for the headless_treemaker Pybind11 extension.
#
# Builds tmModel (Source/tmModel) as a static library WITHOUT wxWidgets/TMWX,
# then compiles TreemakerWrapper.cpp into a Python extension module.
#
#   cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
#   cmake --build build -j
#
# Requires: pybind11 (pip install pybind11), a Python dev environment.
# NOTE: if cmake is unavailable, build.sh performs the equivalent clang++ build.
# ---------------------------------------------------------------------------
cmake_minimum_required(VERSION 3.15)
project(headless_treemaker LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# Locate the vendored TreeMaker source tree.
set(TM_SRC   "${CMAKE_CURRENT_SOURCE_DIR}/../treemaker/Source")
set(TM_MODEL "${TM_SRC}/tmModel")

# --- tmModel static library (headless) ---------------------------------------
# Recursive *.cpp, but EXCLUDE the wnlib subtree: it is the alternate optimizer
# backend (tmUSE_WNLIB, off) and wnparvect.cpp references unbuilt wnlib symbols.
file(GLOB_RECURSE MODEL_SOURCES "${TM_MODEL}/*.cpp")
list(FILTER MODEL_SOURCES EXCLUDE REGEX "/wnlib/")

add_library(tmmodel_headless STATIC
    ${MODEL_SOURCES}
    ${TM_SRC}/tmHeader.cpp
    ${TM_SRC}/tmPrec.cpp
)

# Deliberately define NONE of TMWX / TMDEBUG / TMPROFILE:
#   no TMWX  -> tmHeader.h skips wx/wx.h (pure C++)
#   no TMDEBUG/TMPROFILE -> TM_LOG_ENABLED off -> TMLOG() and the unguarded
#   wxString::Format args in tmPart.cpp compile out.
target_compile_definitions(tmmodel_headless PUBLIC NDEBUG)
set_target_properties(tmmodel_headless PROPERTIES POSITION_INDEPENDENT_CODE ON)

target_include_directories(tmmodel_headless PUBLIC
    ${TM_SRC}
    ${TM_MODEL}
    ${TM_MODEL}/tmNLCO
    ${TM_MODEL}/tmSolvers
    ${TM_MODEL}/tmOptimizers
    ${TM_MODEL}/tmTreeClasses
    ${TM_MODEL}/tmPtrClasses
    ${TM_MODEL}/wnlib
    ${TM_MODEL}/wnlib/cmp
    ${TM_MODEL}/wnlib/conjdir
    ${TM_MODEL}/wnlib/cpy
    ${TM_MODEL}/wnlib/list
    ${TM_MODEL}/wnlib/low
    ${TM_MODEL}/wnlib/mat
    ${TM_MODEL}/wnlib/mem
    ${TM_MODEL}/wnlib/random
    ${TM_MODEL}/wnlib/vect
)

# --- Pybind11 extension module -----------------------------------------------
find_package(pybind11 CONFIG REQUIRED)
pybind11_add_module(headless_treemaker TreemakerWrapper.cpp)
target_link_libraries(headless_treemaker PRIVATE tmmodel_headless)
