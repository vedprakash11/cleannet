package com.ved.cleannet

/**
 * On-device stub for policy layer “ML”. **Remote path:** [ClassificationClient] + your classifier API URL.
 */
object UrlClassifier {

    enum class Category {
        SAFE,
        ADULT,
        UNKNOWN
    }

    /**
     * @param host lowercase hostname
     * @param fullUrl optional full URL for future features
     */
    @Suppress("UNUSED_PARAMETER")
    fun classify(host: String, fullUrl: String? = null): Category = Category.UNKNOWN
}
