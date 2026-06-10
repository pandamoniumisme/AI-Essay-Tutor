package com.aitutor.app

import android.content.Context
import com.aitutor.core.GradeRequest
import com.aitutor.core.GradeResponse
import com.aitutor.core.OcrLine
import com.aitutor.core.RubricComment
import com.aitutor.core.RubricScores
import com.aitutor.core.TranscribeResponse
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

typealias ProgressCb = (message: String, fraction: Double) -> Unit

/**
 * On-device inference. Two implementations:
 *   * [StubInference]  — Phase 1: canned responses, no model. Lets the whole
 *     SPA + bridge + capture flow be validated on the real phone with zero ML.
 *   * LlamaInference    — Phase 2+: real Qwen3.5-2B via llama.cpp JNI.
 *
 * Results are returned as JSON strings in the same shape the web /api endpoints
 * produce, so the SPA renders them unchanged.
 */
interface Inference {
    suspend fun transcribe(payloadJson: String, onProgress: ProgressCb): String
    suspend fun grade(payloadJson: String, onProgress: ProgressCb): String
    fun health(): String

    companion object {
        val json = Json { encodeDefaults = true; ignoreUnknownKeys = true }

        // The router dispatches each call by the user's Settings (offline vs
        // online provider).
        fun create(context: Context): Inference = RouterInference(context.applicationContext, json)

        /** Offline engine: real llama.cpp when its native lib is present, else
         *  the canned stub so the app still runs (build without the lib / demo). */
        fun offline(context: Context, json: Json): Inference =
            if (nativeAvailable()) LlamaInference(context, json) else StubInference(context, json)

        private fun nativeAvailable(): Boolean =
            try { LlamaJni.ensureLoaded(); true } catch (_: Throwable) { false }
    }
}

/** Canned responses so Phase 1 can verify UI + bridge end-to-end. */
class StubInference(private val context: Context, private val json: Json) : Inference {

    override suspend fun transcribe(payloadJson: String, onProgress: ProgressCb): String {
        onProgress("transcribing (stub)", 0.5)
        val language = runCatching {
            json.parseToJsonElement(payloadJson).jsonObject["language"]?.jsonPrimitive?.content
        }.getOrNull() ?: "zh-Hans"

        val essay = if (language == "zh-Hans")
            "今天我和家人去巴刹买菜。我看见许多人在排队。" else
            "Yesterday I goed to the park with my freind. We had alot of fun."
        val resp = TranscribeResponse(
            language = language,
            confidence = 1.0,
            questionText = "=== Prompt ===\n(stub question)\n\n=== Pictures ===\n(stub)",
            essayText = essay,
            essayLines = essay.split("\n").filter { it.isNotBlank() }.map { OcrLine(it) },
        )
        onProgress("done", 1.0)
        return json.encodeToString(TranscribeResponse.serializer(), resp)
    }

    override suspend fun grade(payloadJson: String, onProgress: ProgressCb): String {
        onProgress("grading (stub)", 0.5)
        val req = json.decodeFromString(GradeRequest.serializer(), payloadJson)
        val (_, _, maxTotal) = com.aitutor.core.GradeSchema.caps(req.language, req.paperType)
        val anchor = req.essayText.trim().take(8)
        val resp = GradeResponse(
            scores = RubricScores(
                content = maxTotal * 0.35,
                language = maxTotal * 0.35,
                total = maxTotal * 0.7,
                maxTotal = maxTotal.toDouble(),
                band = 3,
            ),
            comments = if (anchor.isNotEmpty())
                listOf(RubricComment(span = anchor, commentText = "(stub) good opening", category = "praise"))
            else emptyList(),
            overallFeedback = "(stub) This is a placeholder grade so the results screen can be tested without a model.",
        )
        onProgress("done", 1.0)
        return json.encodeToString(GradeResponse.serializer(), resp)
    }

    // Reports real device RAM + the RAM-based recommendation (model not yet
    // downloaded in the stub), so the setup screen shows it on the real phone.
    override fun health(): String =
        ModelStatus.healthJson(context, modelReady = false, activeModel = "stub")
}
