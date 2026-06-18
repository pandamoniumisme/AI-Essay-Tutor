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

    /** Ollama native API base (strip a trailing /v1) for the unload call. */
    private fun nativeBase(base: String): String {
        val b = base.trim().trimEnd('/')
        return if (b.endsWith("/v1")) b.removeSuffix("/v1") else b
    }

    /** Best-effort unload of an Ollama model (keep_alive=0) so it frees memory.
     *  Silent no-op if the server isn't Ollama or is unreachable. */
    suspend fun unload(base: String, model: String) = withContext(Dispatchers.IO) {
        if (base.isBlank() || model.isBlank()) return@withContext
        try {
            val conn = (URL("${nativeBase(base)}/api/generate").openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 3_000
                readTimeout = 5_000
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
            }
            val body = buildJsonObject { put("model", model); put("keep_alive", 0) }.toString()
            conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            conn.responseCode  // trigger the request
            conn.disconnect()
        } catch (_: Exception) {
            // ignore — unloading is an optimisation, not required
        }
    }

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
