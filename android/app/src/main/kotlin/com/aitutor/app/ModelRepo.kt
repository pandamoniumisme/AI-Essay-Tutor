package com.aitutor.app

import com.aitutor.core.ModelChoice

/**
 * Where the on-device GGUF weights + vision projector come from, per model.
 *
 * IMPORTANT: the URLs below are placeholders. Qwen3.5 GGUF builds + their
 * `mmproj` vision projectors must be confirmed against an actual Hugging Face
 * repo before release (filenames and quant tags vary by uploader). Edit the
 * `weightsUrl`/`mmprojUrl`/`sha256` here, or drop a `models.json` override into
 * the app's files dir. The downloader verifies sha256 when one is provided.
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
