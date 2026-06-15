package com.aitutor.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.net.HttpURLConnection
import java.net.URL

/**
 * A Qwen server on the local network reached over an OpenAI-compatible API
 * (Ollama / llama.cpp server / LM Studio). The user enters a base URL like
 * `http://192.168.1.50:11434/v1`; we derive the chat + models endpoints and can
 * probe reachability before grading.
 */
object LocalServer {

    /** Normalise a user-entered base to a ".../chat/completions" URL. */
    fun chatUrl(base: String): String {
        val b = base.trim().trimEnd('/')
        if (b.isEmpty()) return b
        return when {
            b.endsWith("/chat/completions") -> b
            b.endsWith("/v1") -> "$b/chat/completions"
            else -> "$b/v1/chat/completions"
        }
    }

    private fun modelsUrl(base: String): String =
        chatUrl(base).removeSuffix("/chat/completions") + "/models"

    /** Quick reachability check (GET /models, 4s). Returns JSON {ok, detail}. */
    suspend fun probe(base: String): String = withContext(Dispatchers.IO) {
        if (base.isBlank()) return@withContext result(false, "Enter a server URL first.")
        try {
            val conn = (URL(modelsUrl(base)).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 4_000
                readTimeout = 4_000
            }
            val code = conn.responseCode  // any HTTP response means the server is up
            conn.disconnect()
            result(code in 200..499, "Reachable (HTTP $code).")
        } catch (e: Exception) {
            result(false, "Not reachable — same Wi-Fi? (${e.message ?: "no response"})")
        }
    }

    private fun result(ok: Boolean, detail: String): String =
        buildJsonObject { put("ok", ok); put("detail", detail) }.toString()
}
