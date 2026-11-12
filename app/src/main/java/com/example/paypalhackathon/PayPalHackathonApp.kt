
package com.example.paypalhackathon

import android.app.Activity
import android.app.Application
import android.content.Intent
import android.os.Bundle
import com.example.paypalhackaton.ChatHeadService

class PayPalHackathonApp : Application(),
    Application.ActivityLifecycleCallbacks {

    private var startedActivities = 0

    companion object {

        @Volatile
        var appInForeground = false
            private set
    }

    override fun onCreate() {
        super.onCreate()

        registerActivityLifecycleCallbacks(this)
    }

    private fun updateAppVisibility(foreground: Boolean) {

        appInForeground = foreground
        ChatHeadService.appInForeground = foreground

        if (ChatHeadService.isRunning) {

            val action = if (foreground) {
                ChatHeadService.ACTION_APP_FOREGROUND
            } else {
                ChatHeadService.ACTION_APP_BACKGROUND
            }

            sendBroadcast(
                Intent(action).setPackage(packageName)
            )
        }
    }

    override fun onActivityStarted(activity: Activity) {

        startedActivities++

        if (startedActivities == 1) {
            updateAppVisibility(true)
        }
    }

    override fun onActivityStopped(activity: Activity) {

        startedActivities = (startedActivities - 1).coerceAtLeast(0)

        if (startedActivities == 0) {
            updateAppVisibility(false)
        }
    }

    override fun onActivityCreated(
        activity: Activity,
        savedInstanceState: Bundle?
    ) {}

    override fun onActivityResumed(activity: Activity) {}

    override fun onActivityPaused(activity: Activity) {}

    override fun onActivitySaveInstanceState(
        activity: Activity,
        outState: Bundle
    ) {}

    override fun onActivityDestroyed(activity: Activity) {}
}
