package com.aitutor.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// Mirrors server/aitutor_server/api/schemas.py. Field names serialize to the
// same snake_case JSON the web SPA already consumes, so the front-end renders
// the on-device output unchanged.

@Serializable
data class OcrLine(
    val text: String,
    val confidence: Double = 1.0,
    val bbox: List<Int> = listOf(0, 0, 0, 0),
)

@Serializable
data class TranscribeResponse(
    val language: String,
    val confidence: Double,
    @SerialName("question_text") val questionText: String,
    @SerialName("essay_text") val essayText: String,
    @SerialName("essay_lines") val essayLines: List<OcrLine> = emptyList(),
)

@Serializable
data class GradeRequest(
    val language: String,
    @SerialName("paper_type") val paperType: String = "continuous",
    @SerialName("question_text") val questionText: String,
    @SerialName("essay_text") val essayText: String,
    @SerialName("student_level") val studentLevel: String = "P6",
)

@Serializable
data class TrackedEdit(
    @SerialName("original_span") val originalSpan: String,
    @SerialName("occurrence_index") val occurrenceIndex: Int = 0,
    @SerialName("suggested_replacement") val suggestedReplacement: String,
    val reason: String,
    val category: String,
)

@Serializable
data class RubricComment(
    val span: String,
    @SerialName("occurrence_index") val occurrenceIndex: Int = 0,
    @SerialName("comment_text") val commentText: String,
    val category: String,
)

@Serializable
data class RubricScores(
    val content: Double,
    val language: Double,
    val organization: Double? = null,
    val total: Double,
    @SerialName("max_total") val maxTotal: Double,
    val band: Int,
)

@Serializable
data class GradeResponse(
    val scores: RubricScores,
    @SerialName("tracked_edits") val trackedEdits: List<TrackedEdit> = emptyList(),
    @SerialName("improvement_edits") val improvementEdits: List<TrackedEdit> = emptyList(),
    @SerialName("score_after_v1") val scoreAfterV1: Double? = null,
    @SerialName("target_score") val targetScore: Double? = null,
    val comments: List<RubricComment> = emptyList(),
    @SerialName("overall_feedback") val overallFeedback: String = "",
)
