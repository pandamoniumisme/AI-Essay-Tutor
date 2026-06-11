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

/** User-chosen inference settings, persisted in SharedPreferences. */
data class AppSettings(
    val online: Boolean = false,            // false = on-device (Qwen3.5-4B), true = Hugging Face
    val hfToken: String = "",
    val hfModel: String = OnlineProvider.HUGGINGFACE.defaultModel,
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
            apply()
        }
    }

    /** Settings + device info as JSON for the SPA settings screen. */
    fun uiJson(context: Context): String {
        val s = load(context)
        val gib = 1024.0 * 1024 * 1024
        val ramGb = (DeviceRam.totalBytes(context) / gib * 10).roundToInt() / 10.0
        // Recommended memory for the on-device 4B model (the 4B RAM threshold).
        val minMemoryGb = (ModelAdvisor.HIGH_RAM_THRESHOLD_BYTES / gib * 10).roundToInt() / 10.0
        return buildJsonObject {
            put("online", s.online)
            put("hfToken", s.hfToken)
            put("hfModel", s.hfModel)
            put("offlineModelName", ModelChoice.QWEN_4B.displayName)
            put("ramGb", ramGb)
            put("minMemoryGb", minMemoryGb)
        }.toString()
    }
}
