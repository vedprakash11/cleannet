package com.ved.cleannet

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.view.View
import android.webkit.JavascriptInterface
import android.webkit.URLUtil
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.ByteArrayInputStream

class MainActivity : ComponentActivity() {

    private var classifyGeneration = 0

    @SuppressLint("JavascriptInterface")
    private inner class HtmlBridge {
        /** Called from JS: `CleanNetHtml.onPageHtml(...)`. */
        @JavascriptInterface
        @Suppress("unused")
        fun onPageHtml(pageUrl: String, html: String) {
            runOnUiThread { submitHtmlForClassification(pageUrl, html) }
        }
    }

    private val vpnPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            ContextCompat.startForegroundService(this, Intent(this, DnsVpnService::class.java))
        }
    }

    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) {
        startDnsVpnFlow()
    }

    private lateinit var urlInput: EditText
    private lateinit var webView: WebView
    private lateinit var blockedMessage: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        urlInput = findViewById(R.id.urlInput)
        webView = findViewById(R.id.webView)
        blockedMessage = findViewById(R.id.blockedMessage)
        val goButton: Button = findViewById(R.id.goButton)
        val dnsVpnButton: Button = findViewById(R.id.dnsVpnButton)

        @SuppressLint("SetJavaScriptEnabled")
        val settings = webView.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        webView.addJavascriptInterface(HtmlBridge(), "CleanNetHtml")

        webView.webViewClient = object : WebViewClient() {

            /**
             * Often not called for [WebView.loadUrl] on modern WebView — do not rely on this alone.
             * We still handle link taps and some redirects here.
             */
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (!request.isForMainFrame) return false
                return handleUrlNavigation(request.url.toString())
            }

            @Deprecated("Used for compatibility with older WebView behavior")
            override fun shouldOverrideUrlLoading(view: WebView?, url: String?): Boolean {
                if (url == null) return false
                return handleUrlNavigation(url)
            }

            /**
             * Runs for the main document request before content is delivered (including loads from the Go button).
             * This is the most reliable place to block page loads that bypass shouldOverrideUrlLoading.
             */
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                val url = request.url.toString()
                if (request.isForMainFrame && isBlocked(url)) {
                    runOnUiThread { showBlocked() }
                    return WebResourceResponse(
                        "text/plain",
                        "utf-8",
                        ByteArrayInputStream(ByteArray(0))
                    )
                }
                return super.shouldInterceptRequest(view, request)
            }

            /**
             * Covers redirects and navigation where intercept/order differs across WebView versions.
             */
            override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) {
                super.onPageStarted(view, url, favicon)
                if (url == null) return
                if (isBlocked(url)) {
                    view.stopLoading()
                    showBlocked()
                } else if (!url.startsWith("about:", ignoreCase = true)) {
                    // Don’t clear “blocked” UI for about:blank used internally by WebView
                    hideBlocked()
                }
            }

            override fun onPageFinished(view: WebView, url: String?) {
                super.onPageFinished(view, url)
                if (url.isNullOrBlank() || url.startsWith("about:", ignoreCase = true)) return
                if (!resources.getBoolean(R.bool.classifier_api_enabled)) return
                lifecycleScope.launch {
                    val configured = getString(R.string.classifier_api_endpoint).trim()
                    val endpoint = ClassifierEndpointResolver.resolveEndpoint(
                        this@MainActivity,
                        configured
                    )
                    if (endpoint.isNullOrEmpty()) return@launch
                    withContext(Dispatchers.Main) {
                        view.evaluateJavascript(
                            "(function(){var h=document.documentElement.outerHTML;" +
                                "if(h.length>120000)h=h.substring(0,120000);" +
                                "CleanNetHtml.onPageHtml(location.href,h);})();",
                            null
                        )
                    }
                }
            }
        }

        goButton.setOnClickListener {
            val prepared = prepareUrl(urlInput.text.toString())
            if (prepared == null) {
                Toast.makeText(this, R.string.invalid_url, Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            if (isBlocked(prepared)) {
                webView.stopLoading()
                showBlocked()
                return@setOnClickListener
            }
            if (!resources.getBoolean(R.bool.classifier_api_enabled)) {
                hideBlocked()
                webView.loadUrl(prepared)
                return@setOnClickListener
            }
            val key = getString(R.string.classifier_api_key)
            lifecycleScope.launch {
                val configured = getString(R.string.classifier_api_endpoint).trim()
                val endpoint = ClassifierEndpointResolver.resolveEndpoint(
                    this@MainActivity,
                    configured
                )
                if (endpoint.isNullOrEmpty()) {
                    withContext(Dispatchers.Main) {
                        Toast.makeText(
                            this@MainActivity,
                            R.string.classifier_unavailable,
                            Toast.LENGTH_SHORT
                        ).show()
                        hideBlocked()
                        webView.loadUrl(prepared)
                    }
                    return@launch
                }
                when (ClassificationClient.classify(endpoint, key, prepared, null)) {
                    ClassificationResult.ADULT -> withContext(Dispatchers.Main) {
                        webView.stopLoading()
                        showBlocked()
                    }
                    ClassificationResult.ERROR -> withContext(Dispatchers.Main) {
                        Toast.makeText(
                            this@MainActivity,
                            R.string.classifier_unavailable,
                            Toast.LENGTH_SHORT
                        ).show()
                        hideBlocked()
                        webView.loadUrl(prepared)
                    }
                    ClassificationResult.SAFE, ClassificationResult.SKIPPED -> withContext(Dispatchers.Main) {
                        hideBlocked()
                        webView.loadUrl(prepared)
                    }
                }
            }
        }

        dnsVpnButton.setOnClickListener {
            if (Build.VERSION.SDK_INT >= 33 &&
                ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) !=
                PackageManager.PERMISSION_GRANTED
            ) {
                notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            } else {
                startDnsVpnFlow()
            }
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (webView.canGoBack()) {
                    webView.goBack()
                } else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })
    }

    private fun submitHtmlForClassification(pageUrl: String, html: String) {
        if (!resources.getBoolean(R.bool.classifier_api_enabled)) return
        if (pageUrl.startsWith("about:", ignoreCase = true)) return
        val key = getString(R.string.classifier_api_key)
        val seq = ++classifyGeneration
        lifecycleScope.launch {
            val configured = getString(R.string.classifier_api_endpoint).trim()
            val endpoint = ClassifierEndpointResolver.resolveEndpoint(
                this@MainActivity,
                configured
            )
            if (endpoint.isNullOrEmpty()) return@launch
            val result = ClassificationClient.classify(endpoint, key, pageUrl, html)
            if (seq != classifyGeneration) return@launch
            when (result) {
                ClassificationResult.ADULT -> {
                    webView.stopLoading()
                    webView.loadUrl("about:blank")
                    showBlocked()
                }
                ClassificationResult.ERROR -> {
                    Toast.makeText(
                        this@MainActivity,
                        R.string.classifier_unavailable,
                        Toast.LENGTH_SHORT
                    ).show()
                }
                ClassificationResult.SAFE, ClassificationResult.SKIPPED -> {}
            }
        }
    }

    private fun startDnsVpnFlow() {
        val prepare = VpnService.prepare(this)
        if (prepare != null) {
            vpnPermissionLauncher.launch(prepare)
        } else {
            ContextCompat.startForegroundService(this, Intent(this, DnsVpnService::class.java))
        }
    }

    private fun isBlocked(url: String): Boolean = PolicyEngine.shouldBlockUrl(url)

    /**
     * @return true if navigation was handled (blocked), false to let WebView load.
     */
    private fun handleUrlNavigation(url: String): Boolean {
        return if (isBlocked(url)) {
            showBlocked()
            true
        } else {
            hideBlocked()
            false
        }
    }

    private fun showBlocked() {
        blockedMessage.visibility = TextView.VISIBLE
        webView.visibility = View.INVISIBLE
    }

    private fun hideBlocked() {
        blockedMessage.visibility = TextView.GONE
        webView.visibility = View.VISIBLE
    }

    /**
     * Trims input, adds https:// when no scheme is present, and validates the result.
     */
    private fun prepareUrl(raw: String): String? {
        val trimmed = raw.trim()
        if (trimmed.isEmpty()) return null

        val withScheme = when {
            trimmed.startsWith("http://", ignoreCase = true) -> trimmed
            trimmed.startsWith("https://", ignoreCase = true) -> trimmed
            else -> "https://$trimmed"
        }

        return if (URLUtil.isValidUrl(withScheme)) withScheme else null
    }

    override fun onDestroy() {
        webView.destroy()
        super.onDestroy()
    }
}
