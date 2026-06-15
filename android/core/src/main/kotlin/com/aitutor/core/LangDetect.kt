package com.aitutor.core

// Port of server/aitutor_server/lang_detect.py. Trivial Unicode-range heuristic
// -- works because PSLE essays are exclusively English or Simplified Chinese.

object LangDetect {
    private val CJK_RANGES = listOf(
        0x4E00..0x9FFF, // CJK Unified Ideographs
        0x3400..0x4DBF, // Extension A
        0xF900..0xFAFF, // Compatibility Ideographs
        0xFF00..0xFFEF, // Half/fullwidth forms
    )

    private fun isCjk(cp: Int): Boolean = CJK_RANGES.any { cp in it }

    /** "zh-Hans" if >= 10% of letter-ish characters are CJK, else "en". */
    fun detect(text: String): String {
        if (text.isEmpty()) return "en"
        var cjk = 0
        var letters = 0
        for (ch in text) {
            val c = isCjk(ch.code)
            if (c) cjk++
            if (ch.isLetter() || c) letters++
        }
        if (letters == 0) return "en"
        return if (cjk.toDouble() / letters >= 0.10) "zh-Hans" else "en"
    }
}
