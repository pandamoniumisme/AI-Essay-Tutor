package com.aitutor.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class GradeValidationTest {

    private fun req(essay: String, language: String = "zh-Hans", paper: String = "continuous") =
        GradeRequest(language = language, paperType = paper, questionText = "题目", essayText = essay)

    @Test
    fun dropsHallucinatedAndNoopEdits() {
        val essay = "小明去学校。他很开心。"
        val raw = """
            {"scores":{"content":12,"language":13,"total":25,"max_total":40,"band":3},
             "tracked_edits":[
               {"original_span":"学校","suggested_replacement":"學校","reason":"繁体","category":"character_error"},
               {"original_span":"不存在的句子","suggested_replacement":"x","reason":"幻觉","category":"spelling"},
               {"original_span":"他很开心","suggested_replacement":"他很开心","reason":"noop","category":"punctuation"}
             ],"improvement_edits":[],"score_after_v1":26,"target_score":33,"overall_feedback":"不错"}
        """.trimIndent()
        val out = GradeValidation.parseAndValidate(raw, req(essay))
        assertEquals(1, out.trackedEdits.size)
        assertEquals("学校", out.trackedEdits[0].originalSpan)
    }

    @Test
    fun clampsTotalAndTarget() {
        val raw = """
            {"scores":{"content":18,"language":18,"total":99,"max_total":36,"band":5},
             "tracked_edits":[],"improvement_edits":[],
             "score_after_v1":50,"target_score":50,"overall_feedback":"good"}
        """.trimIndent()
        val out = GradeValidation.parseAndValidate(raw, req("essay text here", "en", "continuous"))
        assertEquals(36.0, out.scores.total)
        assertTrue(out.targetScore!! <= 36.0)
        assertTrue(out.scoreAfterV1!! <= out.targetScore!!)
    }

    @Test
    fun lenientParseStripsCodeFence() {
        val obj = GradeValidation.parseJsonLenient("```json\n{\"a\": 1}\n```")
        assertTrue(obj.containsKey("a"))
    }

    @Test
    fun closeOpenBracketsRepairsTruncation() {
        val repaired = GradeValidation.closeOpenBrackets("""{"total": 25, "edits": [1, 2,""")
        assertNotNull(repaired)
        val parsed = GradeValidation.parseJsonLenient(repaired)
        assertTrue(parsed.containsKey("total") && parsed.containsKey("edits"))
    }

    @Test
    fun applyEditsReplacesFirstOccurrenceOnly() {
        val edits = listOf(TrackedEdit("the", 0, "a", "r", "spelling"))
        assertEquals("a the the", GradeValidation.applyEditsToText("the the the", edits))
    }

    @Test
    fun improvementEditsValidatedAgainstV1Corrected() {
        // "goed" -> "went" (round 1); a round-2 edit on "went" must survive
        // because it's validated against the v1-corrected text.
        val essay = "I goed to the park."
        val raw = """
            {"scores":{"content":10,"language":10,"total":20,"max_total":36,"band":3},
             "tracked_edits":[{"original_span":"goed","suggested_replacement":"went","reason":"tense","category":"spelling"}],
             "improvement_edits":[{"original_span":"went to the park","suggested_replacement":"strolled to the park","reason":"vivid verb","category":"word_choice"}],
             "score_after_v1":22,"target_score":32,"overall_feedback":"ok"}
        """.trimIndent()
        val out = GradeValidation.parseAndValidate(raw, req(essay, "en", "continuous"))
        assertEquals(1, out.trackedEdits.size)
        assertEquals(1, out.improvementEdits.size)
    }
}
