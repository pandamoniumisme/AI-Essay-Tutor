package com.aitutor.app

import android.content.Context
import com.aitutor.core.GradeRequest
import com.aitutor.core.GradeResponse
import com.aitutor.core.GradeSchema
import com.aitutor.core.GradeValidation
import com.aitutor.core.LangDetect
import com.aitutor.core.OcrLine
import com.aitutor.core.OnlineProvider
import com.aitutor.core.Prompts
import com.aitutor.core.TranscribeResponse
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.addJsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/**
 * Online inference via Hugging Face Inference Providers (OpenAI-compatible).
 * Mirrors the server's providers/client.py, in Kotlin, reusing the shared
 * `core` prompts / schema / validation. Runs natively (not from the WebView)
 * because a browser-origin fetch to these endpoints would be blocked by CORS.
 */
class OnlineInference(
    private val context: Context,
    private val provider: OnlineProvider,
    private val apiKey: String,
    private val model: String,
    private val json: Json,
) : Inference {

    override suspend fun transcribe(payloadJson: String, onProgress: ProgressCb): String {
        requireKey()
        val payload = json.parseToJsonElement(payloadJson).jsonObject
        val requested = payload["language"]?.jsonPrimitive?.content ?: "auto"
        val questionImgs = images(payload, "question_images")
        val essayImgs = images(payload, "essay_images")

        val language = if (requested != "auto") requested else {
            onProgress("detecting language", 0.05)
            LangDetect.detect(visionCall(Prompts.essayPrompt("zh-Hans"), essayImgs.first(), 1500))
        }

        // Plain for-loops (not forEachIndexed/joinToString) so the suspend
        // visionCall is invoked within the coroutine body.
        val essayParts = mutableListOf<String>()
        for ((i, img) in essayImgs.withIndex()) {
            onProgress("transcribing essay (page ${i + 1}/${essayImgs.size})", 0.10 + 0.60 * i / essayImgs.size)
            val t = visionCall(Prompts.essayPrompt(language), img, 1500).trim()
            if (t.isNotEmpty()) essayParts.add(t)
        }
        val essayText = essayParts.joinToString("\n\n")

        onProgress("transcribing question + describing pictures", 0.75)
        val questionParts = mutableListOf<String>()
        for (img in questionImgs) {
            val p = visionCall(Prompts.questionPrompt(language), img, 1200).trim()
            if (p.isNotEmpty()) questionParts.add(p)
        }
        val questionText = questionParts.joinToString("\n\n")

        onProgress("finalising", 0.95)
        val resp = TranscribeResponse(
            language = language,
            confidence = if (essayText.isNotBlank()) 1.0 else 0.0,
            questionText = questionText,
            essayText = essayText,
            essayLines = essayText.split("\n").filter { it.isNotBlank() }.map { OcrLine(it) },
        )
        return json.encodeToString(TranscribeResponse.serializer(), resp)
    }

    override suspend fun grade(payloadJson: String, onProgress: ProgressCb): String {
        requireKey()
        val req = json.decodeFromString(GradeRequest.serializer(), payloadJson)
        onProgress("grading essay", 0.30)

        val system = loadGraderSystem(req.language)
        val user = Prompts.graderUser(req)
        val messages = buildJsonArray {
            addJsonObject { put("role", "system"); put("content", system) }
            addJsonObject { put("role", "user"); put("content", user) }
        }
        val responseFormat = when (provider.structured) {
            "json_schema" -> buildJsonObject {
                put("type", "json_schema")
                putJsonObject("json_schema") {
                    put("name", "grade_response")
                    put("schema", GradeSchema.build(req))
                }
            }
            "json_object" -> buildJsonObject { put("type", "json_object") }
            else -> null  // "none": rely on prompt + lenient parse/validate
        }

        val raw = chat(messages, responseFormat, maxTokens = 1800)
        onProgress("validating output", 0.95)
        val response: GradeResponse = GradeValidation.parseAndValidate(raw, req)
        return json.encodeToString(GradeResponse.serializer(), response)
    }

    override fun health(): String = buildJsonObject {
        put("ok", true)
        put("on_device", false)
        put("provider", provider.id)
        put("provider_label", provider.label)
        put("model", model)
        put("key_present", apiKey.isNotBlank())
    }.toString()

    // --- HTTP ---

    private fun requireKey() {
        if (apiKey.isBlank()) {
            throw IllegalStateException("No API key for ${provider.label}. Add it in Settings.")
        }
    }

    private fun loadGraderSystem(language: String): String {
        val name = if (language == "zh-Hans") "prompts/grader_zh.md" else "prompts/grader_en.md"
        return context.assets.open(name).bufferedReader().use { it.readText() }
    }

    private suspend fun visionCall(prompt: String, image: Img, maxTokens: Int): String {
        val messages = buildJsonArray {
            addJsonObject {
                put("role", "user")
                putJsonArray("content") {
                    addJsonObject {
                        put("type", "image_url")
                        putJsonObject("image_url") { put("url", "data:${image.mime};base64,${image.b64}") }
                    }
                    addJsonObject { put("type", "text"); put("text", prompt) }
                }
            }
        }
        return chat(messages, responseFormat = null, maxTokens = maxTokens)
    }

    private suspend fun chat(messages: JsonArray, responseFormat: JsonObject?, maxTokens: Int): String =
        withContext(Dispatchers.IO) {
            val body = buildJsonObject {
                put("model", model)
                put("temperature", 0)
                put("max_tokens", maxTokens)
                put("messages", messages)
                if (responseFormat != null) put("response_format", responseFormat)
            }.toString()

            val conn = (URL(provider.chatUrl()).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 30_000
                readTimeout = 180_000
                doOutput = true
                setRequestProperty("Authorization", "Bearer $apiKey")
                setRequestProperty("Content-Type", "application/json")
            }
            conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }

            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() } ?: ""
            if (code !in 200..299) {
                throw IOException("${provider.label} HTTP $code: ${text.take(300)}")
            }
            json.parseToJsonElement(text).jsonObject["choices"]!!.jsonArray[0]
                .jsonObject["message"]!!.jsonObject["content"]!!.jsonPrimitive.content.trim()
        }

    private data class Img(val mime: String, val b64: String)

    private fun images(payload: JsonObject, field: String): List<Img> {
        val arr = payload[field]?.jsonArray ?: return emptyList()
        return arr.map {
            val o = it.jsonObject
            Img(
                mime = o["mime"]?.jsonPrimitive?.content ?: "image/jpeg",
                b64 = o["data"]!!.jsonPrimitive.content,
            )
        }
    }
}
