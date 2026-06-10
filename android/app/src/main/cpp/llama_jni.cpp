// JNI bridge over llama.cpp for on-device Qwen3.5 (text grading + vision OCR).
//
// STATUS: bring-up scaffold. The text-generation path is written against the
// stable llama.h C API; the vision path uses libmtmd. Both are pinned to a
// specific llama.cpp checkout (see CMakeLists.txt) and need on-device
// verification — the mtmd API and the Qwen3.5 media-marker/chat template are
// version-sensitive. Compile this only after vendoring llama.cpp (the app's
// externalNativeBuild is off by default).
//
// Matches the external decls in com.aitutor.app.LlamaJni.

#include <jni.h>
#include <android/log.h>
#include <string>
#include <vector>

#include "llama.h"
#include "json-schema-to-grammar.h"   // common: json_schema_to_grammar()
#include "mtmd.h"                       // libmtmd: vision
#include "mtmd-helper.h"

#define LOG(...) __android_log_print(ANDROID_LOG_INFO, "aitutor-llama", __VA_ARGS__)

namespace {

struct Engine {
    llama_model*        model  = nullptr;
    llama_context*      ctx    = nullptr;
    mtmd_context*       mctx   = nullptr;   // null until a vision call loads it
    const llama_vocab*  vocab  = nullptr;
    std::string         mmproj_path;
    int                 n_ctx  = 8192;
};

std::string jstr(JNIEnv* env, jstring s) {
    if (!s) return {};
    const char* c = env->GetStringUTFChars(s, nullptr);
    std::string out(c ? c : "");
    if (c) env->ReleaseStringUTFChars(s, c);
    return out;
}

// Greedy/grammar-constrained text decode loop. `grammar` may be empty.
std::string generate_text(Engine* e, const std::string& prompt,
                          const std::string& grammar, int max_tokens) {
    const llama_vocab* vocab = e->vocab;

    // Tokenize the prompt.
    int n_prompt = -llama_tokenize(vocab, prompt.c_str(), (int)prompt.size(),
                                   nullptr, 0, true, true);
    std::vector<llama_token> toks(n_prompt);
    llama_tokenize(vocab, prompt.c_str(), (int)prompt.size(),
                   toks.data(), (int)toks.size(), true, true);

    llama_batch batch = llama_batch_get_one(toks.data(), (int)toks.size());
    if (llama_decode(e->ctx, batch) != 0) return {};

    // Sampler chain: grammar (optional) -> greedy.
    llama_sampler* smpl = llama_sampler_chain_init(llama_sampler_chain_default_params());
    if (!grammar.empty()) {
        llama_sampler_chain_add(smpl, llama_sampler_init_grammar(vocab, grammar.c_str(), "root"));
    }
    llama_sampler_chain_add(smpl, llama_sampler_init_greedy());

    std::string out;
    for (int i = 0; i < max_tokens; ++i) {
        llama_token id = llama_sampler_sample(smpl, e->ctx, -1);
        if (llama_vocab_is_eog(vocab, id)) break;
        char piece[256];
        int n = llama_token_to_piece(vocab, id, piece, sizeof(piece), 0, true);
        if (n > 0) out.append(piece, n);
        llama_sampler_accept(smpl, id);
        llama_batch nb = llama_batch_get_one(&id, 1);
        if (llama_decode(e->ctx, nb) != 0) break;
    }
    llama_sampler_free(smpl);
    return out;
}

} // namespace

extern "C" {

JNIEXPORT jlong JNICALL
Java_com_aitutor_app_LlamaJni_loadModel(
        JNIEnv* env, jobject, jstring modelPath, jstring mmprojPath, jint nGpuLayers) {
    llama_backend_init();
    auto* e = new Engine();
    e->mmproj_path = jstr(env, mmprojPath);

    llama_model_params mp = llama_model_default_params();
    mp.n_gpu_layers = nGpuLayers;
    e->model = llama_model_load_from_file(jstr(env, modelPath).c_str(), mp);
    if (!e->model) { LOG("model load failed"); delete e; return 0; }
    e->vocab = llama_model_get_vocab(e->model);

    llama_context_params cp = llama_context_default_params();
    cp.n_ctx = e->n_ctx;
    e->ctx = llama_init_from_model(e->model, cp);
    if (!e->ctx) { LOG("ctx init failed"); llama_model_free(e->model); delete e; return 0; }

    LOG("model loaded (n_gpu_layers=%d)", (int)nGpuLayers);
    return reinterpret_cast<jlong>(e);
}

JNIEXPORT void JNICALL
Java_com_aitutor_app_LlamaJni_freeModel(JNIEnv*, jobject, jlong handle) {
    auto* e = reinterpret_cast<Engine*>(handle);
    if (!e) return;
    if (e->mctx) mtmd_free(e->mctx);
    if (e->ctx) llama_free(e->ctx);
    if (e->model) llama_model_free(e->model);
    delete e;
}

JNIEXPORT jstring JNICALL
Java_com_aitutor_app_LlamaJni_generate(
        JNIEnv* env, jobject, jlong handle, jstring prompt, jstring jsonSchema, jint maxTokens) {
    auto* e = reinterpret_cast<Engine*>(handle);
    if (!e) return env->NewStringUTF("");

    std::string grammar;
    std::string schema = jstr(env, jsonSchema);
    if (!schema.empty()) {
        // common helper: JSON Schema -> GBNF (the on-device analogue of the
        // web build's Gemini response_schema).
        grammar = json_schema_to_grammar(nlohmann::ordered_json::parse(schema));
    }
    llama_memory_clear(llama_get_memory(e->ctx), true);
    std::string out = generate_text(e, jstr(env, prompt), grammar, (int)maxTokens);
    return env->NewStringUTF(out.c_str());
}

JNIEXPORT jstring JNICALL
Java_com_aitutor_app_LlamaJni_generateWithImage(
        JNIEnv* env, jobject, jlong handle, jstring prompt, jbyteArray imageJpeg, jint maxTokens) {
    auto* e = reinterpret_cast<Engine*>(handle);
    if (!e) return env->NewStringUTF("");

    // Lazy-init the multimodal projector on first vision call.
    if (!e->mctx) {
        mtmd_context_params mcp = mtmd_context_params_default();
        e->mctx = mtmd_init_from_file(e->mmproj_path.c_str(), e->model, mcp);
        if (!e->mctx) { LOG("mtmd init failed"); return env->NewStringUTF(""); }
    }

    jsize len = env->GetArrayLength(imageJpeg);
    std::vector<jbyte> buf(len);
    env->GetByteArrayRegion(imageJpeg, 0, len, buf.data());

    // Decode the JPEG into an mtmd bitmap.
    mtmd_bitmap* bmp = mtmd_helper_bitmap_init_from_buf(
        e->mctx, reinterpret_cast<const unsigned char*>(buf.data()), (size_t)len);
    if (!bmp) { LOG("bitmap decode failed"); return env->NewStringUTF(""); }

    // The prompt must contain the model's media marker so mtmd knows where the
    // image embeds. mtmd_default_marker() returns it (e.g. "<__media__>").
    std::string text = std::string(mtmd_default_marker()) + "\n" + jstr(env, prompt);

    mtmd_input_text itext;
    itext.text = text.c_str();
    itext.add_special = true;
    itext.parse_special = true;

    mtmd_input_chunks* chunks = mtmd_input_chunks_init();
    const mtmd_bitmap* bitmaps[] = { bmp };
    if (mtmd_tokenize(e->mctx, chunks, &itext, bitmaps, 1) != 0) {
        LOG("mtmd tokenize failed");
        mtmd_input_chunks_free(chunks);
        mtmd_bitmap_free(bmp);
        return env->NewStringUTF("");
    }

    llama_memory_clear(llama_get_memory(e->ctx), true);
    llama_pos n_past = 0;
    // Eval image+text chunks into the context (helper handles batching).
    if (mtmd_helper_eval_chunks(e->mctx, e->ctx, chunks, /*n_past*/ 0, /*seq_id*/ 0,
                                /*n_batch*/ 512, /*logits_last*/ true, &n_past) != 0) {
        LOG("mtmd eval failed");
        mtmd_input_chunks_free(chunks);
        mtmd_bitmap_free(bmp);
        return env->NewStringUTF("");
    }

    // Continue with a plain greedy text decode (no grammar for transcription).
    llama_sampler* smpl = llama_sampler_chain_init(llama_sampler_chain_default_params());
    llama_sampler_chain_add(smpl, llama_sampler_init_greedy());
    std::string out;
    for (int i = 0; i < (int)maxTokens; ++i) {
        llama_token id = llama_sampler_sample(smpl, e->ctx, -1);
        if (llama_vocab_is_eog(e->vocab, id)) break;
        char piece[256];
        int n = llama_token_to_piece(e->vocab, id, piece, sizeof(piece), 0, true);
        if (n > 0) out.append(piece, n);
        llama_sampler_accept(smpl, id);
        llama_batch nb = llama_batch_get_one(&id, 1);
        if (llama_decode(e->ctx, nb) != 0) break;
    }
    llama_sampler_free(smpl);
    mtmd_input_chunks_free(chunks);
    mtmd_bitmap_free(bmp);
    return env->NewStringUTF(out.c_str());
}

} // extern "C"
