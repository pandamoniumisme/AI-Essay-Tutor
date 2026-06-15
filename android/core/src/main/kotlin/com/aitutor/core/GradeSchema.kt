package com.aitutor.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.add
import kotlinx.serialization.json.addJsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject

// Port of grader._grade_response_json_schema. Produces a JSON Schema describing
// the grade response. On-device, llama.cpp converts this to a GBNF grammar
// (json_schema_to_grammar) to constrain generation -- the structural equivalent
// of the web build's Gemini response_schema. Numeric ranges that a CFG can't
// enforce are clamped afterwards by GradeValidation, exactly as the web build
// does.

object GradeSchema {

    /** (contentMax, languageMax, totalMax) for the route. */
    fun caps(language: String, paperType: String): Triple<Int, Int, Int> = when {
        language == "zh-Hans" -> Triple(20, 20, 40)
        paperType == "situational" -> Triple(6, 8, 14)
        else -> Triple(18, 18, 36)
    }

    private val TRACKED_CATEGORIES = listOf("spelling", "punctuation", "character_error")
    val EDIT_CATEGORIES = listOf(
        "grammar", "spelling", "punctuation", "word_choice",
        "sentence_structure", "character_error",
    )

    private fun editItemSchema(categories: List<String>): JsonObject = buildJsonObject {
        put("type", "object")
        putJsonArray("required") {
            add("original_span"); add("suggested_replacement"); add("reason"); add("category")
        }
        putJsonObject("properties") {
            putJsonObject("original_span") { put("type", "string"); put("minLength", 1); put("maxLength", 200) }
            putJsonObject("occurrence_index") { put("type", "integer"); put("minimum", 0) }
            putJsonObject("suggested_replacement") { put("type", "string"); put("minLength", 1); put("maxLength", 200) }
            putJsonObject("reason") { put("type", "string"); put("minLength", 1); put("maxLength", 160) }
            putJsonObject("category") {
                put("type", "string")
                putJsonArray("enum") { categories.forEach { add(it) } }
            }
        }
    }

    fun build(req: GradeRequest): JsonObject {
        val (contentMax, languageMax, totalMax) = caps(req.language, req.paperType)
        val targetFloor = minOf(32, totalMax)
        return buildJsonObject {
            put("type", "object")
            putJsonArray("required") {
                add("scores"); add("tracked_edits"); add("improvement_edits")
                add("score_after_v1"); add("target_score"); add("overall_feedback")
            }
            putJsonObject("properties") {
                putJsonObject("scores") {
                    put("type", "object")
                    putJsonArray("required") {
                        add("content"); add("language"); add("total"); add("max_total"); add("band")
                    }
                    putJsonObject("properties") {
                        putJsonObject("content") { put("type", "number"); put("minimum", 0); put("maximum", contentMax) }
                        putJsonObject("language") { put("type", "number"); put("minimum", 0); put("maximum", languageMax) }
                        putJsonObject("organization") { put("type", "number"); put("nullable", true) }
                        putJsonObject("total") { put("type", "number"); put("minimum", 0); put("maximum", totalMax) }
                        putJsonObject("max_total") { put("type", "number"); put("minimum", totalMax); put("maximum", totalMax) }
                        putJsonObject("band") { put("type", "integer"); put("minimum", 1); put("maximum", 5) }
                    }
                }
                putJsonObject("tracked_edits") {
                    put("type", "array"); put("maxItems", 30)
                    put("items", editItemSchema(TRACKED_CATEGORIES))
                }
                putJsonObject("improvement_edits") {
                    put("type", "array"); put("maxItems", 15)
                    put("items", editItemSchema(EDIT_CATEGORIES))
                }
                putJsonObject("score_after_v1") { put("type", "number"); put("minimum", 0); put("maximum", totalMax) }
                putJsonObject("target_score") {
                    put("type", "number")
                    put("minimum", minOf(targetFloor, totalMax)); put("maximum", totalMax)
                }
                putJsonObject("overall_feedback") { put("type", "string"); put("maxLength", 1200) }
            }
        }
    }

    fun buildString(req: GradeRequest): String =
        Json.encodeToString(JsonObject.serializer(), build(req))
}
