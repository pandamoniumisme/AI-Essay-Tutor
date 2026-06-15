package com.aitutor.app

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.MediaStore
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import androidx.webkit.WebViewAssetLoader
import java.io.File

/**
 * Hosts the existing web SPA in a WebView and wires the native inference bridge.
 *
 * The SPA is copied into assets at build time (see app/build.gradle.kts) from
 * server/aitutor_server/static, so the capture -> review -> annotated-results
 * UI is identical to the web build. api.js detects window.AndroidBridge and
 * routes transcribe()/grade() here instead of to HTTP.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var cameraImageUri: Uri? = null

    // Gallery / generic file picker (input WITHOUT capture).
    private val pickFiles = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        val uris = WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data)
        fileCallback?.onReceiveValue(uris)
        fileCallback = null
    }

    // Camera capture (input WITH capture="environment"). The photo lands at
    // cameraImageUri (a FileProvider uri); we hand that back to the WebView.
    private val takePicture = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        val uri = if (result.resultCode == Activity.RESULT_OK) cameraImageUri else null
        fileCallback?.onReceiveValue(if (uri != null) arrayOf(uri) else null)
        fileCallback = null
    }

    private fun launchCamera(): Boolean {
        val intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE)
        if (intent.resolveActivity(packageManager) == null) return false
        val file = File.createTempFile("capture_", ".jpg", cacheDir)
        val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", file)
        cameraImageUri = uri
        intent.putExtra(MediaStore.EXTRA_OUTPUT, uri)
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        takePicture.launch(intent)
        return true
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        webView = WebView(this)
        setContentView(webView)

        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false   // assets are served via WebViewAssetLoader, not file://
        }

        // Serve bundled assets over a real https origin so ES modules + fetch
        // work. file:// is an opaque origin where Chromium blocks module scripts
        // (which is why a file:// load showed only the unstyled shell).
        val assetLoader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()
        webView.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(
                view: WebView,
                request: WebResourceRequest,
            ): WebResourceResponse? = assetLoader.shouldInterceptRequest(request.url)
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerForActivityResult(ActivityResultContracts.RequestPermission()) {}
                .launch(android.Manifest.permission.POST_NOTIFICATIONS)
        }

        val bridge = AndroidBridge(webView, Inference.create(applicationContext))
        webView.addJavascriptInterface(bridge, "AndroidBridge")

        webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                view: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                params: FileChooserParams?,
            ): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = filePathCallback
                return try {
                    // A capture-enabled input ("📷 Camera") opens the camera;
                    // otherwise the gallery / file picker.
                    if (params?.isCaptureEnabled == true && launchCamera()) true
                    else { pickFiles.launch(params?.createIntent()); true }
                } catch (e: Exception) {
                    fileCallback = null
                    false
                }
            }
        }

        webView.loadUrl("https://appassets.androidplatform.net/assets/www/index.html")
    }

    override fun onDestroy() {
        webView.destroy()
        super.onDestroy()
    }
}
