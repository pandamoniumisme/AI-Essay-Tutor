package com.aitutor.app

import android.app.ActivityManager
import android.content.Context
import com.aitutor.core.ModelAdvisor
import com.aitutor.core.ModelChoice
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlin.math.roundToInt

/** Total physical RAM (bytes) reported by the OS. */
object DeviceRam {
    fun totalBytes(context: Context): Long {
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val info = ActivityManager.MemoryInfo()
        am.getMemoryInfo(info)
        return info.totalMem
    }

    fun recommend(context: Context): ModelChoice =
        ModelAdvisor.recommend(totalBytes(context))
}

/** Builds the /api/health-shaped JSON the SPA reads, with the on-device
 *  RAM-based model recommendation included so setup can show it before download. */
object ModelStatus {
    fun healthJson(context: Context, modelReady: Boolean, activeModel: String): String {
        val ramBytes = DeviceRam.totalBytes(context)
        val ramGb = (ramBytes.toDouble() / (1024 * 1024 * 1024) * 10).roundToInt() / 10.0
        val rec = ModelAdvisor.recommend(ramBytes)
        return buildJsonObject {
            put("ok", true)
            put("on_device", true)
            put("gemini_key_present", false)
            put("ram_gb", ramGb)
            put("recommended_model", rec.id)
            put("recommended_model_name", rec.displayName)
            put("recommended_download_gb", rec.approxDownloadGb)
            put("model_ready", modelReady)
            put("model", activeModel)
            put("grade_model", activeModel)
        }.toString()
    }
}
