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
    private const val GIB = 1024L * 1024 * 1024

    // A "12 GB" phone reports a bit less than 12 GiB of totalMem because some
    // RAM is reserved (firmware/GPU), so comparing against a strict 12 GiB would
    // misclassify real 12 GB devices as low-RAM. Use 11 GiB as the 12-GB-class
    // cutoff. Raise to 12 if you want a stricter rule.
    const val HIGH_RAM_THRESHOLD_BYTES = 11L * GIB

    fun recommend(totalRamBytes: Long): ModelChoice =
        if (totalRamBytes >= HIGH_RAM_THRESHOLD_BYTES) ModelChoice.QWEN_4B else ModelChoice.QWEN_2B
}
