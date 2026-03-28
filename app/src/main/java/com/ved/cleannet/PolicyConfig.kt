package com.ved.cleannet

import android.content.Context
import org.json.JSONObject
import java.io.File

/**
 * Feasible subset of a Zscaler-style **policy engine**: schedules + layer toggles.
 * (Enterprise features like SSL MITM, identity, and cloud DLP are out of scope for this app.)
 */
data class PolicyConfig(
    val scheduleEnabled: Boolean,
    /** When [scheduleEnabled], blocking runs only if local time hour is inside [windowStartHour, windowEndHour] (supports overnight spans). */
    val windowStartHour: Int,
    val windowEndHour: Int,
    val layerDomainBlocklistAndKeywords: Boolean,
    /** Reserved for on-device/server ML; see [UrlClassifier]. */
    val layerMlClassifier: Boolean
) {
    companion object {
        val DEFAULT = PolicyConfig(
            scheduleEnabled = false,
            windowStartHour = 0,
            windowEndHour = 23,
            layerDomainBlocklistAndKeywords = true,
            layerMlClassifier = false
        )

        private const val ASSET = "policy.json"
        private const val LOCAL = "policy.json"

        fun load(context: Context): PolicyConfig {
            val app = context.applicationContext
            val fromAsset = readAsset(app) ?: DEFAULT
            val local = File(app.filesDir, LOCAL)
            return if (local.isFile) readJson(local.readText()) ?: fromAsset else fromAsset
        }

        private fun readAsset(context: Context): PolicyConfig? =
            try {
                context.assets.open(ASSET).bufferedReader().use { readJson(it.readText()) }
            } catch (_: Exception) {
                null
            }

        private fun readJson(json: String): PolicyConfig? = try {
            val root = JSONObject(json)
            val schedule = root.optJSONObject("schedule") ?: JSONObject()
            val window = schedule.optJSONObject("enforceBlockingOnlyBetweenHours") ?: JSONObject()
            val layers = root.optJSONObject("layers") ?: JSONObject()
            PolicyConfig(
                scheduleEnabled = schedule.optBoolean("enabled", false),
                windowStartHour = window.optInt("start", 0).coerceIn(0, 23),
                windowEndHour = window.optInt("end", 23).coerceIn(0, 23),
                layerDomainBlocklistAndKeywords = layers.optBoolean("domainBlocklistAndKeywords", true),
                layerMlClassifier = layers.optBoolean("mlClassifier", false)
            )
        } catch (_: Exception) {
            null
        }
    }
}
