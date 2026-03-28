package com.ved.cleannet

import android.content.Context
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import java.util.concurrent.ConcurrentHashMap

/**
 * **System-wide (DNS) visibility** while [DnsVpnService] is running.
 *
 * Any app (Chrome, etc.) whose DNS queries are routed through the VPN tunnel to the
 * configured resolvers (see [DnsVpnService]) will have **hostnames** observed here.
 *
 * **Not full URLs** — only the name resolved in DNS (e.g. `www.google.com`), not paths or queries.
 * **Private DNS** (DNS-over-TLS in Android settings) may bypass this VPN path.
 * **DoH/DoT inside the app** can also bypass classic UDP/53 interception.
 */
object GlobalDnsMonitor {

    private const val TAG = "CleanNetDNS"

    /** Min interval between identical hostnames in logcat (ms). */
    private const val LOG_THROTTLE_MS = 4_000L

    /** Min interval between remote classify calls for the same host (ms). */
    private const val CLASSIFY_COOLDOWN_MS = 45_000L

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val lastLogAt = ConcurrentHashMap<String, Long>()
    private val lastClassifyAt = ConcurrentHashMap<String, Long>()

    /**
     * Called for each DNS query hostname seen by [DnsVpnService] (UDP/53 through the tunnel).
     */
    fun onDnsHostname(context: Context, host: String) {
        val h = host.lowercase().trim()
        if (h.isEmpty() || h == "localhost") return

        val app = context.applicationContext
        val now = System.currentTimeMillis()

        if (app.resources.getBoolean(R.bool.dns_monitor_logcat)) {
            val prev = lastLogAt[h] ?: 0L
            if (now - prev >= LOG_THROTTLE_MS) {
                lastLogAt[h] = now
                Log.i(TAG, "lookup host=$h (Chrome & other apps using this DNS path)")
            }
        }

        if (!app.resources.getBoolean(R.bool.classifier_api_enabled)) return
        if (!app.resources.getBoolean(R.bool.dns_monitor_remote_classify)) return

        val prevC = lastClassifyAt[h] ?: 0L
        if (now - prevC < CLASSIFY_COOLDOWN_MS) return
        lastClassifyAt[h] = now

        scope.launch {
            val configured = app.getString(R.string.classifier_api_endpoint).trim()
            val endpoint = ClassifierEndpointResolver.resolveEndpoint(app, configured)
            if (endpoint.isNullOrEmpty()) return@launch
            val key = app.getString(R.string.classifier_api_key)
            val url = "https://$h/"
            try {
                val result = ClassificationClient.classify(endpoint, key, url, null)
                if (result == ClassificationResult.ADULT) {
                    Log.w(TAG, "classified adult host=$h (policy layer uses Blocklist; add domain there to block DNS)")
                }
            } catch (_: Exception) {
            }
        }
    }
}
