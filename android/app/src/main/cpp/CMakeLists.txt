# Native engine build (Qwen3.5 via llama.cpp). OFF by default — the app's
# externalNativeBuild is commented out in app/build.gradle.kts so the APK builds
# without the NDK. To enable on a machine with the NDK + a device for bring-up:
#
#   1. Vendor llama.cpp (pin a recent commit — Qwen3.5 Gated DeltaNet + libmtmd
#      vision only exist in newer checkouts):
#        git submodule add https://github.com/ggml-org/llama.cpp \
#            android/app/src/main/cpp/llama.cpp
#   2. Uncomment externalNativeBuild in app/build.gradle.kts.
#   3. Build; iterate on the mtmd/grammar API against the pinned tag.

cmake_minimum_required(VERSION 3.22.1)
project(aitutor_llama CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(LLAMA_DIR ${CMAKE_CURRENT_SOURCE_DIR}/llama.cpp)

# GPU backend on Adreno: try Vulkan first; fall back to CPU if unavailable.
# (Decide Vulkan vs OpenCL by measurement during bring-up.)
set(GGML_VULKAN ON CACHE BOOL "" FORCE)
set(LLAMA_CURL OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)

add_subdirectory(${LLAMA_DIR} ${CMAKE_BINARY_DIR}/llama_build)

add_library(aitutor_llama SHARED llama_jni.cpp)

# llama (core), common (json_schema_to_grammar), mtmd (vision).
target_include_directories(aitutor_llama PRIVATE
    ${LLAMA_DIR}/include
    ${LLAMA_DIR}/common
    ${LLAMA_DIR}/tools/mtmd
)

find_library(log-lib log)
target_link_libraries(aitutor_llama llama common mtmd ${log-lib})
