package com.aitutor.app

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.RandomAccessFile
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/**
 * Resumable model download into the app's files dir, with progress + optional
 * sha256 verification. No third-party HTTP dependency (HttpURLConnection).
 *
 * Each file downloads to `<name>.part` with HTTP Range resume, then is verified
 * and renamed into place. Already-present (verified) files are skipped.
 */
class ModelDownloader(private val modelDir: File) {

    data class Progress(val file: String, val downloadedBytes: Long, val totalBytes: Long)

    init { modelDir.mkdirs() }

    fun isPresent(name: String): Boolean = File(modelDir, name).exists()

    /** Download both files for a model unless already present. */
    suspend fun ensure(files: ModelFiles, onProgress: (Progress) -> Unit) {
        download(files.weightsName, files.weightsUrl, files.weightsSha256, onProgress)
        download(files.mmprojName, files.mmprojUrl, files.mmprojSha256, onProgress)
    }

    suspend fun download(
        name: String,
        url: String,
        sha256: String?,
        onProgress: (Progress) -> Unit,
    ) = withContext(Dispatchers.IO) {
        val target = File(modelDir, name)
        if (target.exists()) return@withContext

        val part = File(modelDir, "$name.part")
        var existing = if (part.exists()) part.length() else 0L

        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 30_000
            readTimeout = 60_000
            if (existing > 0) setRequestProperty("Range", "bytes=$existing-")
        }
        conn.connect()

        // If the server ignored the Range request, restart from scratch.
        if (existing > 0 && conn.responseCode != HttpURLConnection.HTTP_PARTIAL) {
            existing = 0L
            part.delete()
        }
        if (conn.responseCode !in 200..299) {
            throw java.io.IOException("download failed for $name: HTTP ${conn.responseCode}")
        }

        val contentLen = conn.contentLengthLong.let { if (it > 0) it + existing else -1L }
        RandomAccessFile(part, "rw").use { raf ->
            raf.seek(existing)
            conn.inputStream.use { input ->
                val buf = ByteArray(1 shl 16)
                var downloaded = existing
                var lastReport = 0L
                while (true) {
                    val n = input.read(buf)
                    if (n < 0) break
                    raf.write(buf, 0, n)
                    downloaded += n
                    if (downloaded - lastReport > 2_000_000) { // report every ~2 MB
                        onProgress(Progress(name, downloaded, contentLen))
                        lastReport = downloaded
                    }
                }
                onProgress(Progress(name, downloaded, contentLen))
            }
        }

        if (sha256 != null) {
            val actual = sha256Of(part)
            if (!actual.equals(sha256, ignoreCase = true)) {
                part.delete()
                throw java.io.IOException("checksum mismatch for $name: got $actual")
            }
        }
        if (!part.renameTo(target)) {
            throw java.io.IOException("could not finalise $name")
        }
        Log.i("ModelDownloader", "downloaded $name (${target.length()} bytes)")
    }

    private fun sha256Of(f: File): String {
        val md = MessageDigest.getInstance("SHA-256")
        f.inputStream().use { input ->
            val buf = ByteArray(1 shl 16)
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                md.update(buf, 0, n)
            }
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }
}
