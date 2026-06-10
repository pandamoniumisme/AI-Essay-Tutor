package com.aitutor.app

import android.content.Context
import android.util.Base64
import com.aitutor.core.GradeRequest
import com.aitutor.core.GradeResponse
import com.aitutor.core.GradeSchema
import com.aitutor.core.GradeValidation
import com.aitutor.core.LangDetect
import com.aitutor.core.OcrLine
import com.aitutor.core.Prompts
import com.aitutor.core.TranscribeResponse
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File

/**
 * Phase 2+: real on-device inference with Qwen3.5-2B via [LlamaJni].
 *
 * This is the wiring that turns the verified `core` (prompts, schema,
 * validation, lang detect) into transcription + grading. The native model
 * load/download (Phase 4) is left as TODO; everything around it is the final
 * shape. Not yet built here — needs the NDK + a llama.cpp checkout + the phone.
 *
 * Memory plan (8 GB): one model instance, reused. Grading runs text-only so the
 * vision encoder can be dropped to free RAM for KV cache.
 */
class LlamaInference(
    private val context: Context,
    private val json: Json,
) : Inference {

    // Chosen from device RAM at setup (< 12 GB-class -> 2B, else 4B).
    private val recommended by lazy { DeviceRam.recommend(context) }
    private val modelDir: File get() = File(context.filesDir, "models")
    private val modelPath get() = File(modelDir, "${recommended.id}-q4.gguf").absolutePath
    private val mmprojPath get() = File(modelDir, "${recommended.id}-mmproj.gguf").absolutePath

    private var handle: Long = 0L

    private fun ensureModel() {
        if (handle != 0L) return
        // TODO(Phase 4): download the RECOMMENDED model's GGUF + mmproj into
        // modelDir if absent (resumable + checksum). recommended.id selects 2B/4B.
        check(File(modelPath).exists()) { "model not downloaded yet" }
        LlamaJni.ensureLoaded()
        handle = LlamaJni.loadModel(modelPath, mmprojPath, nGpuLayers = 99)
    }

    override suspend fun transcribe(payloadJson: String, onProgress: ProgressCb): String {
        ensureModel()
        val payload = json.parseToJsonElement(payloadJson).jsonObject
        val requested = payload["language"]?.jsonPrimitive?.content ?: "auto"
        val questionImgs = decodeImages(payloadJson, "question_images")
        val essayImgs = decodeImages(payloadJson, "essay_images")

        val language = if (requested != "auto") requested else {
            onProgress("detecting language", 0.05)
            LangDetect.detect(LlamaJni.generateWithImage(handle, Prompts.essayPrompt("zh-Hans"), essayImgs.first(), 1500))
        }

        val essayParts = mutableListOf<String>()
        essayImgs.forEachIndexed { i, img ->
            onProgress("transcribing essay (page ${i + 1}/${essayImgs.size})", 0.10 + 0.60 * i / essayImgs.size)
            val text = LlamaJni.generateWithImage(handle, Prompts.essayPrompt(language), img, 1500).trim()
            if (text.isNotEmpty()) essayParts.add(text)
        }
        val essayText = essayParts.joinToString("\n\n")

        onProgress("transcribing question + describing pictures", 0.75)
        val questionText = questionImgs.joinToString("\n\n") {
            LlamaJni.generateWithImage(handle, Prompts.questionPrompt(language), it, 1200).trim()
        }

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
        ensureModel()
        val req = json.decodeFromString(GradeRequest.serializer(), payloadJson)
        onProgress("grading essay", 0.30)

        // TODO(Phase 2): load grader_{en,zh}.md from assets/prompts as the system text.
        val system = loadGraderSystem(req.language)
        val prompt = Prompts.chatPrompt(system, Prompts.graderUser(req))
        val schema = GradeSchema.buildString(req)

        val raw = LlamaJni.generate(handle, prompt, jsonSchema = schema, maxTokens = 1800)
        onProgress("validating output", 0.95)
        val response: GradeResponse = GradeValidation.parseAndValidate(raw, req)
        return json.encodeToString(GradeResponse.serializer(), response)
    }

    override fun health(): String =
        ModelStatus.healthJson(context, modelReady = File(modelPath).exists(), activeModel = recommended.id)

    private fun loadGraderSystem(language: String): String {
        val name = if (language == "zh-Hans") "prompts/grader_zh.md" else "prompts/grader_en.md"
        return context.assets.open(name).bufferedReader().use { it.readText() }
    }

    /** Pull base64 image parts out of the bridge payload into JPEG byte arrays. */
    private fun decodeImages(payloadJson: String, field: String): List<ByteArray> {
        val arr = json.parseToJsonElement(payloadJson).jsonObject[field]?.jsonArray ?: return emptyList()
        return arr.map { Base64.decode(it.jsonObject["data"]!!.jsonPrimitive.content, Base64.DEFAULT) }
    }
}
