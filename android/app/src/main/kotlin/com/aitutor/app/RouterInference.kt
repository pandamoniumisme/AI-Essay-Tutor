package com.aitutor.app

import android.content.Context
import com.aitutor.core.OnlineProvider
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put

/**
 * Dispatches each request by the user's current [Settings] mode: on-device,
 * a Qwen server on the local network, or Hugging Face (cloud). Settings are
 * read per call so a Settings change takes effect immediately.
 */
class RouterInference(private val context: Context, private val json: Json) : Inference {

    private val offline by lazy { Inference.offline(context, json) }

    private fun backend(s: AppSettings): Inference = when (s.mode) {
        "hf" -> OnlineInference(
            context,
            chatUrl = OnlineProvider.HUGGINGFACE.chatUrl(),
            label = OnlineProvider.HUGGINGFACE.label,
            transcribeModel = s.hfModelResolved(),
            gradeModel = s.hfModelResolved(),
            apiKey = s.hfToken,
            requiresKey = true,
            structured = OnlineProvider.HUGGINGFACE.structured,
            json = json,
        )
        "local" -> OnlineInference(
            context,
            chatUrl = LocalServer.chatUrl(s.localUrl),
            label = "Local server",
            transcribeModel = s.localReadModelResolved(),
            gradeModel = s.localGradeModelResolved(),
            apiKey = "",
            requiresKey = false,
            structured = "none",
            json = json,
            unloadBase = if (s.localUnloadReader) s.localUrl else null,
        )
        else -> offline
    }

    override suspend fun transcribe(payloadJson: String, onProgress: ProgressCb): String =
        backend(Settings.load(context)).transcribe(payloadJson, onProgress)

    override suspend fun grade(payloadJson: String, onProgress: ProgressCb): String =
        backend(Settings.load(context)).grade(payloadJson, onProgress)

    override fun health(): String {
        val s = Settings.load(context)
        val base = when (s.mode) {
            "hf" -> buildJsonObject {
                put("ok", true); put("on_device", false)
                put("provider_label", "Hugging Face"); put("model", s.hfModelResolved())
                put("key_present", s.hfToken.isNotBlank())
            }.toString()
            "local" -> buildJsonObject {
                put("ok", true); put("on_device", false)
                put("provider_label", "Local server")
                val r = s.localReadModelResolved(); val g = s.localGradeModelResolved()
                put("model", if (r == g) g else "$r → $g")
                put("key_present", s.localUrl.isNotBlank())  // URL set; reachability is the Test button
            }.toString()
            else -> offline.health()
        }
        val o = json.parseToJsonElement(base).jsonObject
        return buildJsonObject {
            o.forEach { (k, v) -> put(k, v) }
            put("mode", s.mode)
        }.toString()
    }
}
