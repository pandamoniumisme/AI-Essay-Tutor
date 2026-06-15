package com.aitutor.core

// Picks which on-device model to recommend from the device's total RAM, BEFORE
// any download. Pure + testable; the actual RAM read lives in the app module
// (DeviceRam). Rule: < 12 GB-class -> 2B, otherwise 4B.

enum class ModelChoice(
    val id: String,
    val displayName: String,
    /** Approx total first-run download incl. the vision projector (GGUF + mmproj). */
    val approxDownloadGb: Double,
) {
    QWEN_2B("qwen3.5-2b", "Qwen3.5-2B", 2.0),
    QWEN_4B("qwen3.5-4b", "Qwen3.5-4B", 3.5);

    companion object {
        fun fromId(id: String?): ModelChoice? = entries.firstOrNull { it.id == id }
    }
}

object ModelAdvisor {
    // 10.5 GiB cutoff for the 4B model. A "12 GB" phone reports only ~10.9 GiB
    // of totalMem (firmware/GPU reserve some), so 10.5 puts 12-GB-class devices
    // on 4B while 8-GB devices (~7.4 GiB) stay on 2B. (= 10.5 * 1024^3 bytes.)
    const val HIGH_RAM_THRESHOLD_BYTES = 11_274_289_152L

    fun recommend(totalRamBytes: Long): ModelChoice =
        if (totalRamBytes >= HIGH_RAM_THRESHOLD_BYTES) ModelChoice.QWEN_4B else ModelChoice.QWEN_2B
}
