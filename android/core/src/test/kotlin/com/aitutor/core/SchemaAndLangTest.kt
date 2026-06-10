package com.aitutor.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class SchemaAndLangTest {

    @Test
    fun capsByRoute() {
        assertEquals(Triple(20, 20, 40), GradeSchema.caps("zh-Hans", "continuous"))
        assertEquals(Triple(18, 18, 36), GradeSchema.caps("en", "continuous"))
        assertEquals(Triple(6, 8, 14), GradeSchema.caps("en", "situational"))
    }

    @Test
    fun schemaStringHasEnumsAndCaps() {
        val zh = GradeSchema.buildString(GradeRequest(language = "zh-Hans", questionText = "q", essayText = "e"))
        assertTrue(zh.contains("character_error"))
        assertTrue(zh.contains("\"maximum\":20"))
        // Round-1 tracked edits restrict categories; grammar must NOT allow word_choice there.
        assertTrue(zh.contains("\"spelling\""))
    }

    @Test
    fun situationalTargetFloorClampedToMax() {
        val sit = GradeSchema.buildString(
            GradeRequest(language = "en", paperType = "situational", questionText = "q", essayText = "e"),
        )
        // target_score minimum is min(32, 14) == 14 for the 14-mark paper.
        assertTrue(sit.contains("\"minimum\":14"))
    }

    @Test
    fun langDetect() {
        assertEquals("zh-Hans", LangDetect.detect("小明去学校"))
        assertEquals("en", LangDetect.detect("hello world this is english"))
        assertEquals("en", LangDetect.detect(""))
    }
}
