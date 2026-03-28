package com.ved.cleannet

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

/**
 * Resolves the POST URL for `/v1/classify`:
 * 1. Non-empty [classifier_api_endpoint] string → use as-is (manual override).
 * 2. Else cached value from last successful discovery.
 * 3. Else UDP broadcast to find a PC running the Flask discovery responder on the same LAN.
 */
object ClassifierEndpointResolver {

    private const val PREFS = "cleannet_classifier"
    private const val KEY_ENDPOINT = "discovered_api_endpoint"
    private const val DISCOVERY_PORT = 45322
    private const val PROBE = "CLEANNET_DISCOVER_V1\n"
    private const val PREFIX = "CLEANNET_API|"

    suspend fun resolveEndpoint(context: Context, configuredOverride: String): String? {
        val trimmed = configuredOverride.trim()
        if (trimmed.isNotEmpty()) return trimmed

        val prefs = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val cached = prefs.getString(KEY_ENDPOINT, null)?.trim().orEmpty()
        if (cached.startsWith("http://", ignoreCase = true) || cached.startsWith("https://", ignoreCase = true)) {
            return cached
        }

        val discovered = discoverOnce()
        if (!discovered.isNullOrEmpty()) {
            prefs.edit().putString(KEY_ENDPOINT, discovered).apply()
            return discovered
        }
        return null
    }

    /** Drop cache (e.g. after switching networks). */
    fun clearCachedEndpoint(context: Context) {
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .remove(KEY_ENDPOINT)
            .apply()
    }

    private suspend fun discoverOnce(): String? = withContext(Dispatchers.IO) {
        try {
            DatagramSocket().use { socket ->
                socket.broadcast = true
                socket.soTimeout = 4000
                val payload = PROBE.toByteArray(Charsets.UTF_8)
                val packet = DatagramPacket(
                    payload,
                    payload.size,
                    InetAddress.getByName("255.255.255.255"),
                    DISCOVERY_PORT
                )
                socket.send(packet)
                val buf = ByteArray(512)
                val recv = DatagramPacket(buf, buf.size)
                socket.receive(recv)
                val text = String(recv.data, 0, recv.length, Charsets.UTF_8).trim()
                if (!text.startsWith(PREFIX)) return@withContext null
                text.removePrefix(PREFIX).trim().takeIf { it.isNotEmpty() }
            }
        } catch (_: Exception) {
            null
        }
    }
}
