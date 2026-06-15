package com.aitutor.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject

// Port of grader._parse_and_validate (+ helpers). Model-independent: it cleans
// up whatever the on-device model emits -- drops hallucinated/no-op spans,
// clamps scores, computes the v1-corrected text for improvement-edit validation.
// This is the safety net behind the grammar-constrained generation.

object GradeValidation {

    private val lenient = Json { ignoreUnknownKeys = true; isLenient = true }
    private val decoder = Json { ignoreUnknownKeys = true }

    fun parseAndValidate(raw: String, req: GradeRequest): GradeResponse {
        val data = parseJsonLenient(raw)

        val editsKept = mutableListOf<TrackedEdit>()
        for (e in data.arr("tracked_edits")) {
            val obj = e as? JsonObject ?: continue
            val span = obj.str("original_span") ?: ""
            val repl = obj.str("suggested_replacement") ?: ""
            if (span.isEmpty() || !req.essayText.contains(span)) continue
            if (repl == span) continue
            obj.decode(TrackedEdit.serializer())?.let { editsKept.add(it) }
        }

        // improvement_edits validate against the v1-corrected essay.
        val v1Corrected = applyEditsToText(req.essayText, editsKept)
        val impKept = mutableListOf<TrackedEdit>()
        for (e in data.arr("improvement_edits")) {
            val obj = e as? JsonObject ?: continue
            val span = obj.str("original_span") ?: ""
            val repl = obj.str("suggested_replacement") ?: ""
            if (span.isEmpty() || !v1Corrected.contains(span)) continue
            if (repl == span) continue
            obj.decode(TrackedEdit.serializer())?.let { impKept.add(it) }
        }

        val commentsKept = mutableListOf<RubricComment>()
        for (c in data.arr("comments")) {
            val obj = c as? JsonObject ?: continue
            val span = obj.str("span") ?: ""
            if (span.isNotEmpty() && req.essayText.contains(span)) {
                obj.decode(RubricComment.serializer())?.let { commentsKept.add(it) }
            }
        }

        val maxTotal = GradeSchema.caps(req.language, req.paperType).third.toDouble()

        val scoresObj = data["scores"] as? JsonObject ?: JsonObject(emptyMap())
        var total = scoresObj.num("total") ?: 0.0
        if (total > maxTotal) total = maxTotal
        var maxTotalOut = scoresObj.num("max_total") ?: 0.0
        if (maxTotalOut == 0.0) maxTotalOut = maxTotal
        val scores = RubricScores(
            content = scoresObj.num("content") ?: 0.0,
            language = scoresObj.num("language") ?: 0.0,
            organization = scoresObj.num("organization"),
            total = total,
            maxTotal = maxTotalOut,
            band = (scoresObj.num("band") ?: 1.0).toInt().coerceIn(1, 5),
        )

        var target = data.num("target_score")
        if (target != null) {
            val floor = minOf(32.0, maxTotal)
            target = maxOf(target, floor, scores.total)
            target = minOf(target, maxTotal)
        }

        var afterV1 = data.num("score_after_v1")
        if (afterV1 != null) {
            val upper = target ?: maxTotal
            afterV1 = maxOf(afterV1, scores.total)
            afterV1 = minOf(afterV1, upper)
        }

        return GradeResponse(
            scores = scores,
            trackedEdits = editsKept,
            improvementEdits = impKept,
            scoreAfterV1 = afterV1,
            targetScore = target,
            comments = commentsKept,
            overallFeedback = (data.str("overall_feedback") ?: "").trim(),
        )
    }

    /** First-occurrence replace per edit; mirrors grader._apply_edits_to_text. */
    fun applyEditsToText(text: String, edits: List<TrackedEdit>): String {
        var out = text
        for (e in edits) {
            val span = e.originalSpan
            val repl = e.suggestedReplacement
            if (span.isNotEmpty() && repl.isNotEmpty() && span != repl && out.contains(span)) {
                out = out.replaceFirst(span, repl)
            }
        }
        return out
    }

    fun parseJsonLenient(raw: String): JsonObject {
        val candidates = mutableListOf(raw)

        var fenced = raw.trim()
        if (fenced.startsWith("```")) {
            fenced = fenced.replace(Regex("^```[a-zA-Z]*\\n?"), "").replace(Regex("\\n?```\\s*$"), "")
            candidates.add(fenced)
        }

        val first = raw.indexOf('{')
        val last = raw.lastIndexOf('}')
        if (first != -1 && last > first) {
            val sliced = raw.substring(first, last + 1)
            candidates.add(sliced)
            val noTrailing = sliced.replace(Regex(",\\s*([}\\]])"), "$1")
            if (noTrailing != sliced) candidates.add(noTrailing)
        }

        for (c in candidates) {
            runCatching { lenient.parseToJsonElement(c).jsonObject }.getOrNull()?.let { return it }
        }
        closeOpenBrackets(raw)?.let { repaired ->
            runCatching { lenient.parseToJsonElement(repaired).jsonObject }.getOrNull()?.let { return it }
        }
        throw IllegalArgumentException("grader produced invalid JSON")
    }

    /** Best-effort repair of truncated JSON; mirrors grader._close_open_brackets. */
    fun closeOpenBrackets(raw: String): String? {
        val first = raw.indexOf('{')
        if (first == -1) return null
        val s = raw.substring(first)
        var inString = false
        var escape = false
        val stack = ArrayDeque<Char>()
        var lastSafe = -1
        for (i in s.indices) {
            val ch = s[i]
            if (escape) { escape = false; continue }
            if (inString) {
                when (ch) {
                    '\\' -> escape = true
                    '"' -> { inString = false; lastSafe = i }
                }
                continue
            }
            when (ch) {
                '"' -> inString = true
                '{' -> stack.addLast('}')
                '[' -> stack.addLast(']')
                '}', ']' -> { if (stack.isNotEmpty()) stack.removeLast(); lastSafe = i }
                ',' -> lastSafe = i
            }
        }
        if (lastSafe == -1) return null
        var truncated = s.substring(0, lastSafe + 1).trimEnd().trimEnd(',')
        return truncated + stack.reversed().joinToString("")
    }

    // --- JsonObject helpers ---

    private fun JsonObject.arr(key: String): JsonArray =
        this[key] as? JsonArray ?: JsonArray(emptyList())

    private fun JsonObject.str(key: String): String? =
        (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content

    private fun JsonObject.num(key: String): Double? {
        val p = this[key] as? JsonPrimitive ?: return null
        return if (p.isString) p.content.toDoubleOrNull() else p.doubleOrNull
    }

    private fun <T> JsonObject.decode(serializer: kotlinx.serialization.KSerializer<T>): T? =
        runCatching { decoder.decodeFromJsonElement(serializer, this) }.getOrNull()
}
