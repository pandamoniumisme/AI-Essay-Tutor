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
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.io.File

/**
 * Real on-device inference: Qwen3.5-2B/4B via llama.cpp ([LlamaJni]).
 *
 * Flow: ensure the RAM-recommended model is downloaded -> load it once ->
 * transcribe pages with the vision path -> grade text-only with a
 * grammar-constrained decode -> validate with the shared `core` logic.
 *
 * Verified to compile; on-device runtime (mtmd image handling, the exact
 * Qwen3.5 vision/chat template, real model URLs) needs bring-up on the phone.
 */
class LlamaInference(
    private val context: Context,
    private val json: Json,
) : Inference {

    // The user's Settings pick ("auto" -> RAM-recommended), else the named 2B/4B.
    private val recommended by lazy {
        com.aitutor.core.ModelChoice.fromId(Settings.load(context).offlineModel)
            ?: DeviceRam.recommend(context)
    }
    private val files by lazy { ModelRepo.filesFor(recommended) }
    private val modelDir get() = File(context.filesDir, "models")
    private val downloader by lazy { ModelDownloader(modelDir) }

    private val modelPath get() = File(modelDir, files.weightsName).absolutePath
    private val mmprojPath get() = File(modelDir, files.mmprojName).absolutePath

    @Volatile private var handle: Long = 0L

    private suspend fun ensureModel(onProgress: ProgressCb) {
        if (handle != 0L) return
        if (!ModelRepo.isConfigured(files)) {
            throw IllegalStateException(
                "model source not configured — set the Qwen3.5 GGUF/mmproj URLs in ModelRepo",
            )
        }
        if (!downloader.isPresent(files.weightsName) || !downloader.isPresent(files.mmprojName)) {
            onProgress("downloading ${recommended.displayName} (~${files.choice.approxDownloadGb} GB)", 0.0)
            downloader.ensure(files) { p ->
                val frac = if (p.totalBytes > 0) (p.downloadedBytes.toDouble() / p.totalBytes) else 0.0
                onProgress("downloading ${p.file}", frac.coerceIn(0.0, 1.0))
            }
        }
        LlamaJni.ensureLoaded()
        onProgress("loading ${recommended.displayName}", 0.05)
        handle = LlamaJni.loadModel(modelPath, mmprojPath, nGpuLayers = 99)
        check(handle != 0L) { "failed to load model" }
    }

    override suspend fun transcribe(payloadJson: String, onProgress: ProgressCb): String {
        ensureModel(onProgress)
        val requested = json.parseToJsonElement(payloadJson).jsonObject["language"]?.jsonPrimitive?.content ?: "auto"
        val questionImgs = decodeImages(payloadJson, "question_images")
        val essayImgs = decodeImages(payloadJson, "essay_images")

        val language = if (requested != "auto") requested else {
            onProgress("detecting language", 0.06)
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
        ensureModel(onProgress)
        val req = json.decodeFromString(GradeRequest.serializer(), payloadJson)

        onProgress("grading essay", 0.30)
        val system = loadGraderSystem(req.language)
        val prompt = Prompts.chatPrompt(system, Prompts.graderUser(req))
        val schema = GradeSchema.buildString(req)

        val raw = LlamaJni.generate(handle, prompt, jsonSchema = schema, maxTokens = 1800)
        onProgress("validating output", 0.95)
        val response: GradeResponse = GradeValidation.parseAndValidate(raw, req)
        return json.encodeToString(GradeResponse.serializer(), response)
    }

    override fun health(): String {
        val configured = ModelRepo.isConfigured(files)
        val ready = configured &&
            downloader.isPresent(files.weightsName) && downloader.isPresent(files.mmprojName)
        val base = ModelStatus.healthJson(context, modelReady = ready, activeModel = recommended.id)
        // Augment with engine-config state without re-deriving RAM fields.
        val obj = json.parseToJsonElement(base).jsonObject
        return buildJsonObject {
            obj.forEach { (k, v) -> put(k, v) }
            put("engine", "llama.cpp")
            put("model_configured", configured)
        }.toString()
    }

    private fun loadGraderSystem(language: String): String {
        val name = if (language == "zh-Hans") "prompts/grader_zh.md" else "prompts/grader_en.md"
        return context.assets.open(name).bufferedReader().use { it.readText() }
    }

    private fun decodeImages(payloadJson: String, field: String): List<ByteArray> {
        val arr = json.parseToJsonElement(payloadJson).jsonObject[field]?.jsonArray ?: return emptyList()
        return arr.map { Base64.decode(it.jsonObject["data"]!!.jsonPrimitive.content, Base64.DEFAULT) }
    }
}
