package com.aitutor.app

import android.app.Service
import android.content.Intent
import android.os.IBinder

/**
 * Phase 4: a foreground service that wraps a transcription/grading run so
 * Android's low-memory killer doesn't terminate the multi-minute job. Declared
 * in the manifest; not yet wired into the bridge.
 */
class InferenceService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null
    // TODO(Phase 4): startForeground() with a progress notification; move the
    // AndroidBridge coroutine work here and post progress to the notification.
}
