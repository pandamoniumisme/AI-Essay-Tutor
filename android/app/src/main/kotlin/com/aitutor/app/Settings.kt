package com.aitutor.app

import android.content.Context
import com.aitutor.core.ModelAdvisor
import com.aitutor.core.ModelChoice
import com.aitutor.core.OnlineProvider
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlin.math.roundToInt

private const val DEFAULT_LOCAL_MODEL = "qwen3.6:35b"

/** User-chosen inference settings, persisted in SharedPreferences. */
data class AppSettings(
    val mode: String = "offline",           // "offline" (Qwen3.5-4B) | "local" | "hf"
    val hfToken: String = "",
    val hfModel: String = OnlineProvider.HUGGINGFACE.defaultModel,
    val localUrl: String = "",              // e.g. http://192.168.1.50:11434/v1
    val localModel: String = DEFAULT_LOCAL_MODEL,
) {
    fun hfModelResolved(): String = hfModel.ifBlank { OnlineProvider.HUGGINGFACE.defaultModel }
    fun localModelResolved(): String = localModel.ifBlank { DEFAULT_LOCAL_MODEL }
}

object Settings {
    private const val PREFS = "aitutor_settings"
    private val json = Json { ignoreUnknownKeys = true }

    fun load(context: Context): AppSettings {
        val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        // Migrate the old boolean ("online" -> "hf").
        val mode = p.getString("mode", null)
            ?: if (p.getBoolean("online", false)) "hf" else "offline"
        return AppSettings(
            mode = mode,
            hfToken = p.getString("hfToken", "") ?: "",
            hfModel = p.getString("hfModel", OnlineProvider.HUGGINGFACE.defaultModel)
                ?: OnlineProvider.HUGGINGFACE.defaultModel,
            localUrl = p.getString("localUrl", "") ?: "",
            localModel = p.getString("localModel", DEFAULT_LOCAL_MODEL) ?: DEFAULT_LOCAL_MODEL,
        )
    }

    /** Merge the given JSON (any subset of fields) into stored settings. */
    fun save(context: Context, payloadJson: String) {
        val cur = load(context)
        val o = json.parseToJsonElement(payloadJson).jsonObject
        fun str(k: String, d: String) = o[k]?.jsonPrimitive?.content ?: d
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().apply {
            putString("mode", str("mode", cur.mode))
            putString("hfToken", str("hfToken", cur.hfToken))
            putString("hfModel", str("hfModel", cur.hfModel))
            putString("localUrl", str("localUrl", cur.localUrl))
            putString("localModel", str("localModel", cur.localModel))
            apply()
        }
    }

    /** Settings + device info as JSON for the SPA settings screen. */
    fun uiJson(context: Context): String {
        val s = load(context)
        val gib = 1024.0 * 1024 * 1024
        val ramGb = (DeviceRam.totalBytes(context) / gib * 10).roundToInt() / 10.0
        val minMemoryGb = (ModelAdvisor.HIGH_RAM_THRESHOLD_BYTES / gib * 10).roundToInt() / 10.0
        return buildJsonObject {
            put("mode", s.mode)
            put("hfToken", s.hfToken)
            put("hfModel", s.hfModel)
            put("localUrl", s.localUrl)
            put("localModel", s.localModel)
            put("offlineModelName", ModelChoice.QWEN_4B.displayName)
            put("ramGb", ramGb)
            put("minMemoryGb", minMemoryGb)
        }.toString()
    }
}
