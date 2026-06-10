package com.aitutor.app

import android.content.Context
import com.aitutor.core.OnlineProvider
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

/** User-chosen inference settings, persisted in SharedPreferences. */
data class AppSettings(
    val online: Boolean = false,            // false = on-device, true = online provider
    val provider: String = "gemini",        // "gemini" | "dashscope"
    val geminiKey: String = "",
    val dashscopeKey: String = "",
    val geminiModel: String = OnlineProvider.GEMINI.defaultModel,
    val dashscopeModel: String = OnlineProvider.DASHSCOPE.defaultModel,
) {
    val activeProvider: OnlineProvider get() = OnlineProvider.from(provider)
    fun keyFor(p: OnlineProvider) = if (p == OnlineProvider.DASHSCOPE) dashscopeKey else geminiKey
    fun modelFor(p: OnlineProvider): String {
        val m = if (p == OnlineProvider.DASHSCOPE) dashscopeModel else geminiModel
        return m.ifBlank { p.defaultModel }
    }
}

object Settings {
    private const val PREFS = "aitutor_settings"
    private val json = Json { ignoreUnknownKeys = true }

    fun load(context: Context): AppSettings {
        val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return AppSettings(
            online = p.getBoolean("online", false),
            provider = p.getString("provider", "gemini") ?: "gemini",
            geminiKey = p.getString("geminiKey", "") ?: "",
            dashscopeKey = p.getString("dashscopeKey", "") ?: "",
            geminiModel = p.getString("geminiModel", OnlineProvider.GEMINI.defaultModel)
                ?: OnlineProvider.GEMINI.defaultModel,
            dashscopeModel = p.getString("dashscopeModel", OnlineProvider.DASHSCOPE.defaultModel)
                ?: OnlineProvider.DASHSCOPE.defaultModel,
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
            putString("provider", str("provider", cur.provider))
            putString("geminiKey", str("geminiKey", cur.geminiKey))
            putString("dashscopeKey", str("dashscopeKey", cur.dashscopeKey))
            putString("geminiModel", str("geminiModel", cur.geminiModel))
            putString("dashscopeModel", str("dashscopeModel", cur.dashscopeModel))
            apply()
        }
    }

    /** Settings as JSON for the SPA settings screen. Keys are never sent raw to
     *  logs; they go only to the WebView the user is already driving. */
    fun toJson(s: AppSettings): String = buildJsonObject {
        put("online", s.online)
        put("provider", s.provider)
        put("geminiKey", s.geminiKey)
        put("dashscopeKey", s.dashscopeKey)
        put("geminiModel", s.geminiModel)
        put("dashscopeModel", s.dashscopeModel)
    }.toString()
}
