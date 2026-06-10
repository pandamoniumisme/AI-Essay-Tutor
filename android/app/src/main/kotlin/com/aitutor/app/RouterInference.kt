package com.aitutor.app

import android.content.Context
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put

/**
 * Dispatches each request by the user's current [Settings]: on-device engine
 * when offline, or the chosen online provider. Settings are read per call so a
 * toggle in the Settings screen takes effect immediately (no restart).
 */
class RouterInference(private val context: Context, private val json: Json) : Inference {

    private val offline by lazy { Inference.offline(context, json) }

    private fun online(s: AppSettings): OnlineInference {
        val p = s.activeProvider
        return OnlineInference(context, p, s.keyFor(p), s.modelFor(p), json)
    }

    override suspend fun transcribe(payloadJson: String, onProgress: ProgressCb): String {
        val s = Settings.load(context)
        return if (s.online) online(s).transcribe(payloadJson, onProgress)
        else offline.transcribe(payloadJson, onProgress)
    }

    override suspend fun grade(payloadJson: String, onProgress: ProgressCb): String {
        val s = Settings.load(context)
        return if (s.online) online(s).grade(payloadJson, onProgress)
        else offline.grade(payloadJson, onProgress)
    }

    override fun health(): String {
        val s = Settings.load(context)
        val base = if (s.online) online(s).health() else offline.health()
        // Tag the mode so the SPA banner can show it.
        val o = json.parseToJsonElement(base).jsonObject
        return buildJsonObject {
            o.forEach { (k, v) -> put(k, v) }
            put("mode", if (s.online) "online" else "offline")
        }.toString()
    }
}
