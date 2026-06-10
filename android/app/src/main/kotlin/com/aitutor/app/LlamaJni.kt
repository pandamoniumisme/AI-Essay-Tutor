package com.aitutor.app

/**
 * JNI surface over llama.cpp (Phase 2). Implemented in src/main/cpp/llama_jni.cpp.
 *
 * The native library is built via CMake against a llama.cpp checkout — see
 * src/main/cpp/CMakeLists.txt and android/README.md. Build is currently disabled
 * in app/build.gradle.kts (externalNativeBuild commented out) so the Phase-1
 * stub app builds without the NDK.
 */
object LlamaJni {
    @Volatile private var loaded = false

    fun ensureLoaded() {
        if (!loaded) { System.loadLibrary("aitutor_llama"); loaded = true }
    }

    /** Load the GGUF (+ optional mmproj vision projector). Returns an opaque handle. */
    external fun loadModel(modelPath: String, mmprojPath: String, nGpuLayers: Int): Long

    external fun freeModel(handle: Long)

    /** Multimodal generate: one image + prompt (used for transcription). */
    external fun generateWithImage(
        handle: Long, prompt: String, imageJpeg: ByteArray, maxTokens: Int,
    ): String

    /**
     * Text-only generate (used for grading). `jsonSchema`, when non-null, is
     * converted to a GBNF grammar by llama.cpp's json_schema_to_grammar to
     * constrain output — the on-device equivalent of Gemini's response_schema.
     */
    external fun generate(handle: Long, prompt: String, jsonSchema: String?, maxTokens: Int): String
}
