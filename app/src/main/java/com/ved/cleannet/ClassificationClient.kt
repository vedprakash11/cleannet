package com.ved.cleannet

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

enum class ClassificationResult {
    SAFE,
    ADULT,
    ERROR,
    SKIPPED
}

/**
 * Remote URL classifier HTTP API.
 *
 * **Expected request:** `POST` [apiEndpoint] with JSON body:
 * `{"url":"<string>","html":"<optional string>"}` (omit or null `html` for URL-only classification).
 *
 * **Expected response:** JSON with `label` set to `"adult"` or `"safe"` (and optional `score`).
 * Point [apiEndpoint] at your deployed service (e.g. FastAPI, Cloud Function, or third-party API).
 */
object ClassificationClient {

    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()

    private val jsonMedia = "application/json; charset=utf-8".toMediaType()

    /**
     * @param apiEndpoint full URL for the classify action, e.g. `https://api.example.com/v1/classify`
     * @param apiKey optional Bearer token; if blank, no Authorization header is sent
     * @param html optional page source; null = URL-only classification
     */
    suspend fun classify(
        apiEndpoint: String,
        apiKey: String,
        pageUrl: String,
        html: String?
    ): ClassificationResult {
        val url = apiEndpoint.trim()
        if (url.isEmpty()) return ClassificationResult.SKIPPED
        return withContext(Dispatchers.IO) {
            try {
                val json = JSONObject().put("url", pageUrl)
                if (html != null) json.put("html", html)
                val body = json.toString().toRequestBody(jsonMedia)
                val builder = Request.Builder().url(url).post(body)
                val key = apiKey.trim()
                if (key.isNotEmpty()) {
                    builder.addHeader("Authorization", "Bearer $key")
                }
                val req = builder.build()
                client.newCall(req).execute().use { resp ->
                    val text = resp.body?.string().orEmpty()
                    if (!resp.isSuccessful) return@withContext ClassificationResult.ERROR
                    val o = JSONObject(text)
                    val label = o.optString("label", "safe")
                    if (label.equals("adult", ignoreCase = true)) ClassificationResult.ADULT
                    else ClassificationResult.SAFE
                }
            } catch (_: Exception) {
                ClassificationResult.ERROR
            }
        }
    }
}
