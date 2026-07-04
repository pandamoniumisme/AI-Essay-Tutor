package com.aitutor.app

import com.aitutor.core.ModelChoice

/**
 * Where the on-device GGUF weights + vision projector come from, per model.
 *
 * IMPORTANT: the URLs below are still placeholders — huggingface.co isn't
 * reachable from the sandbox that last edited this file, so the exact file
 * names + sha256 couldn't be confirmed directly. Candidate repos to check
 * (found via web search, not yet verified):
 *   - https://huggingface.co/unsloth/Qwen3.5-2B-GGUF — quantized weights
 *     (Unsloth's GGUF releases; check for a Q4_K_M-class file).
 *   - https://huggingface.co/prithivMLmods/Qwen3.5-abliterated-MAX-AIO-GGUF —
 *     reportedly ships multiple `mmproj` (vision projector) quantizations
 *     (f32/bf16/f16/q8_0) alongside the weights.
 * Open both repo pages, copy the exact weights/mmproj file URLs, and use
 * Hugging Face's displayed SHA256 (or `sha256sum` the downloaded file) for
 * `weightsSha256`/`mmprojSha256` below — or drop a `models.json` override
 * into the app's files dir. The downloader verifies sha256 when one is
 * provided.
 */
data class ModelFiles(
    val choice: ModelChoice,
    val weightsName: String,
    val weightsUrl: String,
    val weightsSha256: String?,
    val mmprojName: String,
    val mmprojUrl: String,
    val mmprojSha256: String?,
)

object ModelRepo {
    // TODO(confirm): replace with verified Qwen3.5 GGUF + mmproj URLs/checksums.
    private const val PLACEHOLDER = "https://huggingface.co/REPLACE_ME"

    fun filesFor(choice: ModelChoice): ModelFiles = when (choice) {
        ModelChoice.QWEN_2B -> ModelFiles(
            choice = choice,
            weightsName = "qwen3.5-2b-q4_k_m.gguf",
            weightsUrl = "$PLACEHOLDER/qwen3.5-2b-q4_k_m.gguf",
            weightsSha256 = null,
            mmprojName = "qwen3.5-2b-mmproj-f16.gguf",
            mmprojUrl = "$PLACEHOLDER/qwen3.5-2b-mmproj-f16.gguf",
            mmprojSha256 = null,
        )
        ModelChoice.QWEN_4B -> ModelFiles(
            choice = choice,
            weightsName = "qwen3.5-4b-q4_k_m.gguf",
            weightsUrl = "$PLACEHOLDER/qwen3.5-4b-q4_k_m.gguf",
            weightsSha256 = null,
            mmprojName = "qwen3.5-4b-mmproj-f16.gguf",
            mmprojUrl = "$PLACEHOLDER/qwen3.5-4b-mmproj-f16.gguf",
            mmprojSha256 = null,
        )
    }

    fun isConfigured(files: ModelFiles): Boolean =
        !files.weightsUrl.contains("REPLACE_ME") && !files.mmprojUrl.contains("REPLACE_ME")
}
