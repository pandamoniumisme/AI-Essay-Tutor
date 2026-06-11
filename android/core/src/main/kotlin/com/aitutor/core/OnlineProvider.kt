package com.aitutor.core

// The online backend the app can call: Hugging Face Inference Providers
// (OpenAI-compatible router). Mirrors the server's providers/config.py.

enum class OnlineProvider(
    val id: String,
    val label: String,
    /** OpenAI-compatible base; chatUrl() appends "chat/completions". */
    val baseUrl: String,
    val defaultModel: String,
    /** How JSON grade output is constrained: "json_schema" | "json_object" | "none". */
    val structured: String,
) {
    HUGGINGFACE(
        "huggingface", "Hugging Face",
        "https://router.huggingface.co/v1/",
        "Qwen/Qwen3.5-9B", "none",
    );

    fun chatUrl(): String = baseUrl.trimEnd('/') + "/chat/completions"

    companion object {
        val DEFAULT = HUGGINGFACE
        fun from(id: String?): OnlineProvider = DEFAULT
    }
}
