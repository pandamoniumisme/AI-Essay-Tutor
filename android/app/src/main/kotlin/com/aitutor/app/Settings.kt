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

private const val DEFAULT_READ_MODEL = "gemma4:26b"
private const val DEFAULT_GRADE_MODEL = "gemma4:26b"

/** User-chosen inference settings, persisted in SharedPreferences. */
data class AppSettings(
    val mode: String = "offline",           // "offline" (Qwen3.5-4B) | "local" | "hf"
    val hfToken: String = "",
    val hfModel: String = OnlineProvider.HUGGINGFACE.defaultModel,
    val localUrl: String = "",              // e.g. http://192.168.1.50:11434/v1
    // Local mode runs OCR on the reading model and grades on the grade model;
    // the reading model is unloaded after OCR so the (hot) grade model keeps RAM.
    val localReadModel: String = DEFAULT_READ_MODEL,
    val localGradeModel: String = DEFAULT_GRADE_MODEL,
    val localUnloadReader: Boolean = true,
) {
    fun hfModelResolved(): String = hfModel.ifBlank { OnlineProvider.HUGGINGFACE.defaultModel }
    fun localReadModelResolved(): String = localReadModel.ifBlank { DEFAULT_READ_MODEL }
    fun localGradeModelResolved(): String = localGradeModel.ifBlank { DEFAULT_GRADE_MODEL }
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
            localReadModel = p.getString("localReadModel", DEFAULT_READ_MODEL) ?: DEFAULT_READ_MODEL,
            localGradeModel = p.getString("localGradeModel", DEFAULT_GRADE_MODEL) ?: DEFAULT_GRADE_MODEL,
            localUnloadReader = p.getBoolean("localUnloadReader", true),
        )
    }

    /** Merge the given JSON (any subset of fields) into stored settings. */
    fun save(context: Context, payloadJson: String) {
        val cur = load(context)
        val o = json.parseToJsonElement(payloadJson).jsonObject
        fun str(k: String, d: String) = o[k]?.jsonPrimitive?.content ?: d
        fun bool(k: String, d: Boolean) = o[k]?.jsonPrimitive?.content?.toBooleanStrictOrNull() ?: d
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().apply {
            putString("mode", str("mode", cur.mode))
            putString("hfToken", str("hfToken", cur.hfToken))
            putString("hfModel", str("hfModel", cur.hfModel))
            putString("localUrl", str("localUrl", cur.localUrl))
            putString("localReadModel", str("localReadModel", cur.localReadModel))
            putString("localGradeModel", str("localGradeModel", cur.localGradeModel))
            putBoolean("localUnloadReader", bool("localUnloadReader", cur.localUnloadReader))
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
            put("localReadModel", s.localReadModel)
            put("localGradeModel", s.localGradeModel)
            put("localUnloadReader", s.localUnloadReader)
            put("offlineModelName", ModelChoice.QWEN_4B.displayName)
            put("ramGb", ramGb)
            put("minMemoryGb", minMemoryGb)
        }.toString()
    }
}
