package com.aitutor.app

import android.content.Context
import com.aitutor.core.ModelAdvisor
import com.aitutor.core.OnlineProvider
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlin.math.roundToInt

/** User-chosen inference settings, persisted in SharedPreferences. */
data class AppSettings(
    val online: Boolean = false,            // false = on-device, true = Hugging Face
    val hfToken: String = "",
    val hfModel: String = OnlineProvider.HUGGINGFACE.defaultModel,
    // On-device model: "auto" (RAM-recommended), "qwen3.5-2b", or "qwen3.5-4b".
    val offlineModel: String = "auto",
) {
    fun hfModelResolved(): String = hfModel.ifBlank { OnlineProvider.HUGGINGFACE.defaultModel }
}

object Settings {
    private const val PREFS = "aitutor_settings"
    private val json = Json { ignoreUnknownKeys = true }

    fun load(context: Context): AppSettings {
        val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return AppSettings(
            online = p.getBoolean("online", false),
            hfToken = p.getString("hfToken", "") ?: "",
            hfModel = p.getString("hfModel", OnlineProvider.HUGGINGFACE.defaultModel)
                ?: OnlineProvider.HUGGINGFACE.defaultModel,
            offlineModel = p.getString("offlineModel", "auto") ?: "auto",
        )
    }

    /** Merge the given JSON (any subset of fields) into stored settings. */
    fun save(context: Context, payloadJson: String) {
        val cur = load(context)
        val o = json.parseToJsonElement(payloadJson).jsonObject
        fun str(k: String, d: String) = o[k]?.jsonPrimitive?.content ?: d
        fun bool(k: String, d: Boolean) = o[k]?.jsonPrimitive?.content?.toBooleanStrictOrNull() ?: d
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().apply {
            putBoolean("online", bool("online", cur.online))
            putString("hfToken", str("hfToken", cur.hfToken))
            putString("hfModel", str("hfModel", cur.hfModel))
            putString("offlineModel", str("offlineModel", cur.offlineModel))
            apply()
        }
    }

    /** Settings + device info as JSON for the SPA settings screen. */
    fun uiJson(context: Context): String {
        val s = load(context)
        val ramBytes = DeviceRam.totalBytes(context)
        val ramGb = (ramBytes.toDouble() / (1024 * 1024 * 1024) * 10).roundToInt() / 10.0
        val rec = ModelAdvisor.recommend(ramBytes)
        return buildJsonObject {
            put("online", s.online)
            put("hfToken", s.hfToken)
            put("hfModel", s.hfModel)
            put("offlineModel", s.offlineModel)
            put("ramGb", ramGb)
            put("recommendedModel", rec.id)
            put("recommendedModelName", rec.displayName)
        }.toString()
    }
}
