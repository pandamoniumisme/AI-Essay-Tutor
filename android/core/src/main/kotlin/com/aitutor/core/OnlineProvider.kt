package com.aitutor.core

// The online providers the Android app can call (mirrors the server's
// providers/config.py). Both are OpenAI-compatible, so the app uses one HTTP
// client parameterised by these fields.

enum class OnlineProvider(
    val id: String,
    val label: String,
    /** OpenAI-compatible base; chatUrl() appends "chat/completions". */
    val baseUrl: String,
    val defaultModel: String,
    /** How this endpoint enforces JSON grade output. */
    val structured: String,
) {
    GEMINI(
        "gemini", "Gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "gemini-3.5-flash", "json_schema",
    ),
    DASHSCOPE(
        "dashscope", "Alibaba Cloud (Qwen)",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/",
        "qwen3.5-flash", "json_object",
    );

    fun chatUrl(): String = baseUrl.trimEnd('/') + "/chat/completions"

    companion object {
        fun from(id: String?): OnlineProvider = entries.firstOrNull { it.id == id } ?: GEMINI
    }
}
