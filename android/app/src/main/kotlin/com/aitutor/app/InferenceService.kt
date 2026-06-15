package com.aitutor.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat

/**
 * Foreground service that keeps the process alive while a transcription/grading
 * run executes (those take minutes on-device, and Android's low-memory killer
 * would otherwise reclaim a backgrounded app mid-job). The bridge starts it
 * before a job, updates its notification with progress, and stops it after.
 */
class InferenceService : Service() {

    override fun onCreate() {
        super.onCreate()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val mgr = getSystemService(NotificationManager::class.java)
            mgr.createNotificationChannel(
                NotificationChannel(CHANNEL, "Essay grading", NotificationManager.IMPORTANCE_LOW),
            )
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val msg = intent?.getStringExtra(EXTRA_MSG) ?: "Working…"
        startForeground(NOTIF_ID, notification(msg))
        return START_NOT_STICKY
    }

    private fun notification(msg: String): Notification =
        NotificationCompat.Builder(this, CHANNEL)
            .setContentTitle("PSLE Compo Tutor")
            .setContentText(msg)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        private const val CHANNEL = "inference"
        private const val NOTIF_ID = 42
        private const val EXTRA_MSG = "msg"

        fun start(context: Context, msg: String) {
            val i = Intent(context, InferenceService::class.java).putExtra(EXTRA_MSG, msg)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(i)
            else context.startService(i)
        }

        /** Re-issue with a new message to update the ongoing notification. */
        fun update(context: Context, msg: String) = start(context, msg)

        fun stop(context: Context) {
            context.stopService(Intent(context, InferenceService::class.java))
        }
    }
}
