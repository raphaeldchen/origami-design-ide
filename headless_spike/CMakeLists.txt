# Throwaway feasibility spike: build tmModel headless (no TMWX / no wxWidgets)
# and run an ALM scale optimization. NOT product code.
cmake_minimum_required(VERSION 3.15)
project(treemaker_headless_spike LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Path to the vendored TreeMaker source tree.
set(TM_SRC "${CMAKE_CURRENT_SOURCE_DIR}/../treemaker/Source")
set(TM_MODEL "${TM_SRC}/tmModel")

# Mirror the model's own GLOB (recursive *.cpp). The CFSQP/RFSQP/wnlib
# wrappers are #ifdef-guarded off (only tmUSE_ALM is set in tmNLCO.h), so
# they compile to near-empty without their proprietary headers.
file(GLOB_RECURSE MODEL_SOURCES "${TM_MODEL}/*.cpp")

add_executable(spike_main
    spike_main.cpp
    ${MODEL_SOURCES}
    ${TM_SRC}/tmHeader.cpp
    ${TM_SRC}/tmPrec.cpp
)

target_include_directories(spike_main PRIVATE
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

# Deliberately define NONE of: TMWX, TMDEBUG, TMPROFILE.
#   - no TMWX     => tmHeader.h skips wx/wx.h; the model is pure C++
#   - no TMDEBUG/TMPROFILE => TM_LOG_ENABLED off => TMLOG() (and the
#     unguarded wxString::Format args in tmPart.cpp) compile out.
target_compile_definitions(spike_main PRIVATE NDEBUG)
