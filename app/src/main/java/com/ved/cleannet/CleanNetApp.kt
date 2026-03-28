package com.ved.cleannet

import android.app.Application

class CleanNetApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Blocklist.init(applicationContext)
        PolicyEngine.init(applicationContext)
    }
}
