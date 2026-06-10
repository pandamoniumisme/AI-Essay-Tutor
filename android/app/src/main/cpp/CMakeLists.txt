# Phase 2 native build (disabled by default — see app/build.gradle.kts).
#
# Vendor llama.cpp as a submodule, then enable externalNativeBuild:
#   git submodule add https://github.com/ggml-org/llama.cpp \
#       android/app/src/main/cpp/llama.cpp
# Use a recent commit — Qwen3.5's Gated DeltaNet operators and vision (libmtmd)
# support only land in newer llama.cpp.

cmake_minimum_required(VERSION 3.22.1)
project(aitutor_llama)

set(CMAKE_CXX_STANDARD 17)

set(LLAMA_DIR ${CMAKE_CURRENT_SOURCE_DIR}/llama.cpp)

# GPU backend: try Vulkan on Adreno first, OpenCL fallback (decide by measurement).
# set(GGML_VULKAN ON)
# add_subdirectory(${LLAMA_DIR} ${CMAKE_BINARY_DIR}/llama_build)

add_library(aitutor_llama SHARED llama_jni.cpp)

find_library(log-lib log)
# target_link_libraries(aitutor_llama llama mtmd ${log-lib})
target_link_libraries(aitutor_llama ${log-lib})
