// JNI bridge over llama.cpp for on-device Qwen3.5-2B (Phase 2 skeleton).
//
// These signatures match com.aitutor.app.LlamaJni. The bodies are intentionally
// stubs — the real implementation links llama.cpp + libmtmd and is sizeable.
// Integration points (see llama.cpp examples):
//   * loadModel        -> llama_model_load_from_file + (mmproj) mtmd_init_from_file
//   * generateWithImage-> mtmd: tokenize image+text, eval, sample/decode loop
//   * generate         -> json_schema_to_grammar(jsonSchema) -> grammar-constrained
//                         sampler, then the standard decode loop
//
// Build is disabled in app/build.gradle.kts until llama.cpp is vendored.

#include <jni.h>
#include <string>

extern "C" {

JNIEXPORT jlong JNICALL
Java_com_aitutor_app_LlamaJni_loadModel(
        JNIEnv* env, jobject /*thiz*/, jstring modelPath, jstring mmprojPath, jint nGpuLayers) {
    // TODO(Phase 2): load GGUF (+ mmproj). Return an opaque context pointer.
    return 0;
}

JNIEXPORT void JNICALL
Java_com_aitutor_app_LlamaJni_freeModel(JNIEnv* env, jobject /*thiz*/, jlong handle) {
    // TODO(Phase 2): free llama context + model.
}

JNIEXPORT jstring JNICALL
Java_com_aitutor_app_LlamaJni_generateWithImage(
        JNIEnv* env, jobject /*thiz*/, jlong handle, jstring prompt,
        jbyteArray imageJpeg, jint maxTokens) {
    // TODO(Phase 2): mtmd image+text eval -> decode loop -> text.
    return env->NewStringUTF("");
}

JNIEXPORT jstring JNICALL
Java_com_aitutor_app_LlamaJni_generate(
        JNIEnv* env, jobject /*thiz*/, jlong handle, jstring prompt,
        jstring jsonSchema, jint maxTokens) {
    // TODO(Phase 2): if jsonSchema != null, json_schema_to_grammar -> grammar
    // sampler; decode loop -> text.
    return env->NewStringUTF("");
}

} // extern "C"
