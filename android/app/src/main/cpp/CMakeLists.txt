# Native engine build (Qwen3.5 via llama.cpp). OFF by default: app/build.gradle.kts
# only turns on externalNativeBuild when this directory actually contains a
# llama.cpp checkout, so the Phase-1 stub APK still builds without the NDK.
# To enable on a machine with the NDK + a device for bring-up:
#
#   1. Vendor llama.cpp (pin a recent commit — as of mid-2026 Qwen3.5's hybrid
#      Gated-DeltaNet/attention graph and libmtmd vision are still landing on
#      HEAD, not a tagged release; confirm current status before pinning):
#        git submodule add https://github.com/ggml-org/llama.cpp \
#            android/app/src/main/cpp/llama.cpp
#      (CI does the equivalent via a plain checkout in the build-apk-native
#      job — see .github/workflows/android.yml — so a submodule pointer
#      doesn't need to be committed to this repo.)
#   2. Build — externalNativeBuild picks this checkout up automatically.
#   3. Iterate on the mtmd/grammar API against the pinned commit; it is
#      version-sensitive (see llama_jni.cpp).

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
