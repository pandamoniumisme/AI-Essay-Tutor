package com.aitutor.app

import android.webkit.JavascriptInterface
import android.webkit.WebView
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

/**
 * The object exposed to JS as window.AndroidBridge. Each long-running method
 * takes a `token`, does the work off the UI thread, then resolves/rejects the
 * matching JS promise (api.js holds them in a token->promise map).
 *
 * @JavascriptInterface methods run on a WebView binder thread, so they must not
 * touch the WebView directly -- all evaluateJavascript calls are posted back to
 * the UI thread.
 */
class AndroidBridge(
    private val webView: WebView,
    private val inference: Inference,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    @JavascriptInterface
    fun transcribe(token: String, payloadJson: String) {
        run(token) { inference.transcribe(payloadJson) { msg, frac -> progress(token, msg, frac) } }
    }

    @JavascriptInterface
    fun grade(token: String, payloadJson: String) {
        run(token) { inference.grade(payloadJson) { msg, frac -> progress(token, msg, frac) } }
    }

    /** Synchronous: cheap to compute, returns the same shape as /api/health. */
    @JavascriptInterface
    fun health(): String = inference.health()

    /** Current settings (mode, provider, keys, models) as JSON. */
    @JavascriptInterface
    fun getSettings(): String =
        Settings.toJson(Settings.load(webView.context.applicationContext))

    /** Persist a (partial) settings JSON from the Settings screen. */
    @JavascriptInterface
    fun setSettings(payloadJson: String) =
        Settings.save(webView.context.applicationContext, payloadJson)

    private fun run(token: String, work: suspend () -> String) {
        val ctx = webView.context.applicationContext
        scope.launch {
            InferenceService.start(ctx, "Working…")
            try {
                val result = work()
                resolve(token, result)
            } catch (e: Throwable) {
                reject(token, e.message ?: "on-device inference failed")
            } finally {
                InferenceService.stop(ctx)
            }
        }
    }

    private fun resolve(token: String, json: String) =
        eval("window.__nativeResolve(${js(token)}, ${js(json)})")

    private fun reject(token: String, message: String) =
        eval("window.__nativeReject(${js(token)}, ${js(message)})")

    private fun progress(token: String, message: String, fraction: Double) {
        InferenceService.update(webView.context.applicationContext, message)
        eval("window.__nativeProgress(${js(token)}, ${js(message)}, $fraction)")
    }

    private fun eval(code: String) = webView.post { webView.evaluateJavascript(code, null) }

    /** Encode a Kotlin string as a safe JS string literal. */
    private fun js(s: String): String = Json.encodeToString(String.serializer(), s)
}
