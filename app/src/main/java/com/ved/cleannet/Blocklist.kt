package com.ved.cleannet

import android.content.Context
import android.net.Uri
import org.json.JSONObject
import java.io.BufferedReader
import java.io.File
import java.util.Collections
import java.util.HashSet

/**
 * Phase 1: keyword matching ([ASSET_KEYWORDS] JSON + [FALLBACK_KEYWORDS]) and domain blocklist
 * from [ASSET_BLOCKLIST] and optional [LOCAL_BLOCKLIST] in app files dir (merged on top of assets).
 *
 * Domain lists: maintain using public hosts feeds such as
 * [StevenBlack/hosts](https://github.com/StevenBlack/hosts) (see [ASSET_BLOCKLIST] header).
 */
object Blocklist {

    private const val ASSET_BLOCKLIST = "blocklist_domains.txt"
    private const val ASSET_KEYWORDS = "blocklist_keywords.json"
    private const val LOCAL_BLOCKLIST = "blocklist_domains.txt"
    private const val LOCAL_KEYWORDS = "blocklist_keywords.json"

    /**
     * Mirrors [app/src/main/assets/blocklist_keywords.json] — used if JSON fails to load.
     */
    private val FALLBACK_KEYWORDS = listOf(
        "xxx", "porn", "sex", "adult", "nsfw",
        "cam", "cams", "webcam", "livecam",
        "escort", "escorts", "hookup", "dating-sex",
        "nude", "nudity", "naked", "erotic",
        "fetish", "bdsm", "kink",
        "hardcore", "softcore",
        "hentai", "rule34", "doujin",
        "xxxvideo", "pornhub", "xvideo",
        "redtube", "youporn",
        "onlyfans", "fansly",
        "strip", "stripchat",
        "milf", "teen-sex",
        "incest", "taboo",
        "adultchat", "sexchat",
        "pornstar", "camgirl", "camboy",
        "sexvideo", "adultvideo",
        "dating-adult",
        "sexshop", "adultstore",
        "xxxmovies", "adultmovies",
        "pornfree", "freeporn",
        "sexstories", "erotica",
        "liveadult", "adultlive",
        "privatecam", "adultcam",
        "nsfwcontent", "adultcontent"
    )

    /** Substring patterns (loaded from assets JSON, or [FALLBACK_KEYWORDS] if missing). */
    val keywords: List<String>
        get() = keywordList

    private var keywordList: List<String> = FALLBACK_KEYWORDS

    private val domains: MutableSet<String> = Collections.synchronizedSet(HashSet())

    @Volatile
    private var initialized = false

    /**
     * Call once from [Application.onCreate]. Safe to call again (no-op if already initialized).
     */
    fun init(context: Context) {
        if (initialized) return
        synchronized(this) {
            if (initialized) return
            val appContext = context.applicationContext
            keywordList = loadKeywordsJson(appContext) ?: FALLBACK_KEYWORDS
            domains.clear()
            try {
                appContext.assets.open(ASSET_BLOCKLIST).bufferedReader().use { loadFromReader(it) }
            } catch (_: Exception) {
            }
            val localDomains = File(appContext.filesDir, LOCAL_BLOCKLIST)
            if (localDomains.isFile) {
                try {
                    localDomains.bufferedReader().use { loadFromReader(it) }
                } catch (_: Exception) {
                }
            }
            val localKw = File(appContext.filesDir, LOCAL_KEYWORDS)
            if (localKw.isFile) {
                loadKeywordsJsonFile(localKw)?.let { keywordList = it }
            }
            initialized = true
        }
    }

    private fun loadKeywordsJson(context: Context): List<String>? {
        return try {
            context.assets.open(ASSET_KEYWORDS).bufferedReader().use { parseKeywordsJson(it.readText()) }
        } catch (_: Exception) {
            null
        }
    }

    private fun loadKeywordsJsonFile(file: File): List<String>? {
        return try {
            file.readText().let { parseKeywordsJson(it) }
        } catch (_: Exception) {
            null
        }
    }

    private fun parseKeywordsJson(json: String): List<String>? {
        val root = JSONObject(json)
        val arr = root.getJSONArray("keywords")
        return buildList {
            for (i in 0 until arr.length()) {
                val s = arr.getString(i).trim().lowercase()
                if (s.isNotEmpty()) add(s)
            }
        }
    }

    private fun loadFromReader(reader: BufferedReader) {
        reader.useLines { lines ->
            lines.forEach { line ->
                parseLine(line)?.let { domains.add(it) }
            }
        }
    }

    /**
     * Supports:
     * - `example.com`
     * - hosts-style: `0.0.0.0 example.com` or `127.0.0.1 example.com`
     */
    internal fun parseLine(line: String): String? {
        val t = line.substringBefore('#').trim()
        if (t.isEmpty()) return null
        val parts = t.split(Regex("\\s+")).filter { it.isNotEmpty() }
        if (parts.isEmpty()) return null
        val candidate = when {
            parts.size >= 2 && isHostsIp(parts[0]) -> parts[1]
            parts.size == 1 -> parts[0]
            else -> return null
        }
        val normalized = candidate.trim().lowercase()
        if (normalized.isEmpty() || normalized.contains("/")) return null
        return normalized
    }

    private fun isHostsIp(s: String): Boolean =
        s == "0.0.0.0" || s == "127.0.0.1" || s == "::1" || s == "0:0:0:0:0:0:0:0"

    private fun keywordsMatch(text: String): Boolean {
        val lower = text.lowercase()
        return keywords.any { lower.contains(it) }
    }

    /**
     * True if [host] (e.g. from DNS) matches keywords or the domain blocklist (suffix / exact).
     */
    fun matchesHost(host: String): Boolean {
        if (!initialized) return keywordsMatch(host)
        val h = host.trim().lowercase()
        if (h.isEmpty()) return false
        if (keywordsMatch(h)) return true
        return domainListed(h)
    }

    /**
     * WebView / full URL: keywords on full URL plus host-based rules on [Uri.getHost].
     */
    fun matchesUrl(url: String): Boolean {
        if (keywordsMatch(url)) return true
        val host = try {
            Uri.parse(url).host
        } catch (_: Exception) {
            null
        }
        return host != null && matchesHost(host)
    }

    /**
     * Walk labels: `a.b.evil.com` checks `a.b.evil.com`, `b.evil.com`, `evil.com` against the set.
     */
    private fun domainListed(host: String): Boolean {
        val set = domains
        if (set.isEmpty()) return false
        val labels = host.split('.')
        for (i in labels.indices) {
            val suffix = labels.subList(i, labels.size).joinToString(".")
            if (set.contains(suffix)) return true
        }
        return false
    }

    /** Count after init (for debugging / UI). */
    fun domainCount(): Int = domains.size
}
