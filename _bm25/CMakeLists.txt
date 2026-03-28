cmake_minimum_required(VERSION 3.18)
project(cognirepo_bm25 CXX)

# ── guard ─────────────────────────────────────────────────────────────────────
# Default OFF so that a plain  pip install cognirepo  never needs cmake.
# Enable with:
#   cmake -S cognirepo/_bm25 -B build/bm25 -DBUILD_EXT=ON
#   cmake --build build/bm25 --target _bm25_ext
option(BUILD_EXT "Build the C++ pybind11 extension (_bm25_ext)" OFF)

if(NOT BUILD_EXT)
  message(STATUS "[cognirepo] BUILD_EXT=OFF — skipping C++ BM25 extension.")
  message(STATUS "            To compile: cmake ... -DBUILD_EXT=ON")
  return()
endif()

# ── C++ standard ──────────────────────────────────────────────────────────────
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# ── pybind11 ──────────────────────────────────────────────────────────────────
# scikit-build-core / pip provides pybind11 when listed in [build-system].requires
find_package(pybind11 REQUIRED)

# ── target ────────────────────────────────────────────────────────────────────
pybind11_add_module(_bm25_ext
    bm25.cpp
    bindings.cpp
)

target_include_directories(_bm25_ext PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

# Optimisation flags (release mode)
if(CMAKE_BUILD_TYPE STREQUAL "Release")
    target_compile_options(_bm25_ext PRIVATE
        $<$<CXX_COMPILER_ID:GNU,Clang>:-O3 -march=native>
        $<$<CXX_COMPILER_ID:MSVC>:/O2>
    )
endif()

# ── install ───────────────────────────────────────────────────────────────────
# Place the compiled .so next to the _bm25 Python package so the import
# in __init__.py can find it as a top-level module.
install(TARGETS _bm25_ext
        LIBRARY DESTINATION ${CMAKE_SOURCE_DIR}/../../  # repo root
        RUNTIME DESTINATION ${CMAKE_SOURCE_DIR}/../../
)
