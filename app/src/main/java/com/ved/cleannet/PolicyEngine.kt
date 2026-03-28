package com.ved.cleannet

import android.content.Context
import java.util.Calendar

/**
 * **Zscaler-inspired, mobile-feasible pipeline**: schedule → list/keyword layers → optional ML stub.
 *
 * Not implemented (requires enterprise / system keys): TLS MITM, cloud proxy, full DLP, identity.
 */
object PolicyEngine {

    private var config: PolicyConfig = PolicyConfig.DEFAULT

    fun init(context: Context) {
        config = PolicyConfig.load(context)
    }

    fun shouldBlockUrl(url: String): Boolean = evaluateUrl(url).blocked

    fun shouldBlockHost(host: String): Boolean = evaluateHost(host).blocked

    fun evaluateUrl(url: String): PolicyResult {
        if (!enforcementActiveNow()) {
            return PolicyResult(false, "schedule_off_window")
        }
        val host = try {
            android.net.Uri.parse(url).host?.lowercase()?.trim().orEmpty()
        } catch (_: Exception) {
            ""
        }
        if (config.layerMlClassifier) {
            val cat = UrlClassifier.classify(host, url)
            if (cat == UrlClassifier.Category.ADULT) {
                return PolicyResult(true, "ml_adult")
            }
        }
        if (config.layerDomainBlocklistAndKeywords && Blocklist.matchesUrl(url)) {
            return PolicyResult(true, "domain_or_keyword")
        }
        return PolicyResult(false, "allowed")
    }

    fun evaluateHost(host: String): PolicyResult {
        if (!enforcementActiveNow()) {
            return PolicyResult(false, "schedule_off_window")
        }
        val h = host.lowercase().trim()
        if (config.layerMlClassifier) {
            val cat = UrlClassifier.classify(h, null)
            if (cat == UrlClassifier.Category.ADULT) {
                return PolicyResult(true, "ml_adult")
            }
        }
        if (config.layerDomainBlocklistAndKeywords && Blocklist.matchesHost(h)) {
            return PolicyResult(true, "domain_or_keyword")
        }
        return PolicyResult(false, "allowed")
    }

    /**
     * When schedule is disabled: always enforce lists.
     * When enabled: enforce only while local time is inside the configured hour window.
     */
    private fun enforcementActiveNow(): Boolean {
        if (!config.scheduleEnabled) return true
        return isLocalHourInWindow(config.windowStartHour, config.windowEndHour)
    }

    private fun isLocalHourInWindow(start: Int, end: Int): Boolean {
        val h = Calendar.getInstance().get(Calendar.HOUR_OF_DAY)
        return if (start <= end) {
            h in start..end
        } else {
            h >= start || h <= end
        }
    }
}

data class PolicyResult(val blocked: Boolean, val reason: String)
